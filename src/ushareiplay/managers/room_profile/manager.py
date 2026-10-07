"""`RoomProfileManager` —— 房间档案（抽屉会话 + 草稿状态）的唯一所有者。

同一个抽屉承载四类字段：房间标题、房间话题、派对公告、派对类型与推荐分发。
原先它有四个「打开者」各自复制一遍打开 ritual，关闭则靠 `PartyManager` 的
`finally` 兜底，而「在窗口里必须按什么顺序同步」只写在注释里。

现在只有一个模块知道窗口什么时候开着：

    with RoomProfileManager.instance().with_window_open() as open_error:
        if open_error:
            return open_error
        <每个字段只做自己的编辑>

    results = RoomProfileManager.instance().audit_and_repair()   # 一次性全量检查与修正

`with_window_open()` 只在「窗口是它打开的」时候负责关窗；窗口本来就开着时
（例如被外层流程打开），退出后保持原状，让外层决定何时关。

UI 独占性沿用既有做法：本模块的抽屉接口是**同步**的，锁由上游的
`CommandManager.ui_session`（`app_controller.ui_session`）持有。把这里改成
async 会打断剩下的同步调用点（`room_name_manager` / `party_manager`），
因此不做。
"""

import asyncio
import logging
import time
import traceback
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Sequence

from ushareiplay.core.singleton import Singleton
from ushareiplay.helpers.room_banner import TOPIC_MAX_LENGTH, TITLE_MAX_LENGTH, clean_banner_text
from ushareiplay.managers.room_profile.drafts import ProfileDraftStore
from ushareiplay.managers.room_profile.driver import (
    DEFAULT_ENTRY_KEYS,
    RoomProfileDrawerDriverPort,
)
from ushareiplay.state.room_state import RoomState

#: 话题的打开入口。话题原先点的是黑板上的 `room_topic`，而不是抽屉默认的
#: `chat_room_title`；两者指向同一个抽屉，但入口保持不变。
TOPIC_ENTRY_KEYS = ('room_topic',)
#: 抽屉里「自定义话题」的两种皮肤：主色面板与背景板。
TOPIC_EDIT_ENTRY_KEYS = ('edit_topic_entry', 'edit_topic_bg_entry')
#: 提交后用来判断结果的屏幕：编辑层还在 = 改得太频繁；聊天框回来了 = 成功。
TOPIC_SUBMIT_PROBE_KEYS = ('input_box_entry', 'edit_topic_confirm')
#: 确认提交之后等 Appium 落地的静默时间（秒）。离线测试把它置 0。
TOPIC_SETTLE_SECONDS = 1.0

#: 抽屉里「自定义公告」的两种皮肤：新建时是「自定义」，改已有公告时是「修改自定义」。
NOTICE_CUSTOMIZE_ENTRY_KEYS = ('customize_notice_button', 'modify_notice_button')
#: 关闭公告编辑层的按钮（不是关抽屉）。既用它判断编辑层是否弹出，也用它收尾。
NOTICE_CLOSE_KEY = 'close_notice'
#: 抽屉里公告那一行的入口与输入/提交。
NOTICE_EDIT_ENTRY_KEY = 'edit_notice_entry'
NOTICE_INPUT_KEY = 'edit_notice_input'
NOTICE_CONFIRM_KEY = 'edit_notice_confirm'
#: 抽屉里显示当前公告文案的元素（只有审计读它）。
NOTICE_TEXT_KEY = 'chat_room_notice'
#: 没有配置时的兜底，与旧 `NoticeManager.get_default_notice` 逐字一致。
DEFAULT_NOTICE_FALLBACK = 'U Share I Play\n分享音乐 享受快乐'
SYSTEM_DEFAULT_NOTICES_FALLBACK = ['弹唱大会', 'Souler们在随便聊聊ing', '蹲一个人']


class RoomProfileManager(Singleton):
    """打开、检测、关闭房间信息抽屉，并拥有窗口内的全量审计顺序。"""

    def __init__(self, handler=None, drawer_driver: Optional[RoomProfileDrawerDriverPort] = None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._drawer_driver = drawer_driver
        self._drafts = ProfileDraftStore()
        self.pending_audit_retry = False
        self.last_audit_results: Dict = {}
        # 已经写进黑板的话题。冷启动时为 None，与旧 TopicManager 同义。
        self.current_topic = None
        self.topic_settle_seconds = TOPIC_SETTLE_SECONDS

    @property
    def handler(self):
        return self._handler

    @property
    def drafts(self) -> ProfileDraftStore:
        """三个字段的冷却与待写入文案。"""
        return self._drafts

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, 'logger', None) or logging.getLogger("RoomProfileManager")
        return self._logger

    @property
    def drawer_driver(self):
        """抽屉 UI 端口。None 表示尚未装配适配器（离线装配或接线漏了）。"""
        return self._drawer_driver

    def adopt_handler(self, handler, drawer_driver=None) -> None:
        """把 handler（可选地连同它的端口）接过来。

        只给过渡期的 `RoomInfoWindow` 门面用：既有的调用点与测试把 handler
        注入到那个窗口上，而真实实现在本模块里。#394 删掉门面后本方法一并删除。
        """
        if handler is not None:
            self._handler = handler
            self._logger = getattr(handler, "logger", self._logger)
        if drawer_driver is not None:
            self._drawer_driver = drawer_driver

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """窗口（抽屉）当前是否开着。端口未装配时一律回答「关着」。"""
        driver = self.drawer_driver
        if driver is None:
            return False
        return bool(driver.is_open())

    def ensure_open(
        self,
        entry_keys: Optional[Sequence[str]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        """确保窗口已打开；已开着则直接返回。

        Args:
            entry_keys: 打开入口，默认 chat_room_title -> room_topic
            error_message: 打不开时返回给调用方的文案。调用方原样传入自己面向
                           用户的报错文本，以免统一入口后改变聊天气泡里的报错。

        Returns:
            error dict 表示打不开，None 表示窗口可用。
        """
        if self.is_open():
            return None

        driver = self.drawer_driver
        if driver is None:
            if self.handler is None:
                return {'error': error_message or 'Soul handler is not available'}
            # handler 在、端口不在：这是组合根漏了接线，不是业务失败。
            # 悄悄降级成「App 不可用」会让生产环境的抽屉写入整条链路静默失效。
            raise RuntimeError(
                "RoomProfileManager drawer actions require a RoomProfileDrawerDriverPort adapter; "
                "construct RoomProfileManager with drawer_driver=... at the composition root."
            )

        for entry_key in entry_keys or DEFAULT_ENTRY_KEYS:
            result = driver.open_drawer(
                entry_key,
                error_message=error_message or f'Failed to open room info window via {entry_key}',
            )
            if not (isinstance(result, dict) and "error" in result):
                return None
            self.logger.warning(f"Room info window entry '{entry_key}' failed, trying next entry")

        return {'error': error_message or 'Failed to open room info window'}

    def ensure_closed(self) -> None:
        """确保窗口已关闭，恢复至主房间界面。

        优先使用 UI 正规关窗操作（点遮罩关抽屉）；仅在抽屉关窗未成功且弹窗标志
        依然存留时，才使用 press_back() 作为最后的保底防御，防止因过快盲按
        press_back() 导致误退出派对房间。
        """
        try:
            if not self.is_open():
                return

            self.logger.info("Room info window is open, attempting to close via close_drawer UI action")
            if self._require_driver().close_drawer():
                self.logger.info("Successfully closed room info window via close_drawer")
                return

            self.logger.warning("close_drawer did not close room info window, falling back to press_back")
            self._require_driver().press_back()
        except Exception as e:
            self.logger.warning(f"Error ensuring room info window closed: {e}")

    @contextmanager
    def with_window_open(
        self,
        entry_keys: Optional[Sequence[str]] = None,
        error_message: Optional[str] = None,
    ) -> Iterator[Optional[dict]]:
        """窗口开着的上下文：需要时才打开，且只关掉自己打开的那一次。

        Args:
            entry_keys: 打开入口，默认 chat_room_title -> room_topic。
            error_message: 打不开时返回给调用方的文案，透传给 `ensure_open`，
                以免统一入口后改变聊天气泡里的报错。

        Yields:
            error dict（打开失败）或 None（窗口可用、可以开始编辑）。
            打开失败时不会 yield 一个「假装开着」的窗口，调用方据此提前返回。
        """
        if self.is_open():
            yield None
            return

        open_error = self.ensure_open(entry_keys, error_message)
        if open_error:
            yield open_error
            return

        try:
            yield None
        finally:
            self.ensure_closed()

    def close_with_back(self) -> None:
        """关掉编辑层后回到主界面：先按一次返回，必要时再按一次。

        用于「编辑对话框之上还有一层抽屉」的场景（例如推荐分发选项）。
        """
        try:
            self._require_driver().press_back()
            if self.is_open():
                self.logger.info("Room info window still visible after back, pressing back again to exit")
                self._require_driver().press_back()
        except Exception as e:
            self.logger.warning(f"Error closing room info window with back: {e}")

    def _require_driver(self) -> RoomProfileDrawerDriverPort:
        driver = self.drawer_driver
        if driver is None:
            raise RuntimeError(
                "RoomProfileManager drawer actions require a RoomProfileDrawerDriverPort adapter; "
                "construct RoomProfileManager with drawer_driver=... at the composition root."
            )
        return driver

    # ------------------------------------------------------------------
    # 字段草稿：排队 -> 冷却 -> 写 UI
    # ------------------------------------------------------------------
    #
    # 话题（#390）与公告（#391）两条都已经是完整纵切：`set_xxx` 排队、
    # `update_xxx` 在冷却到期后经端口写 UI。房名与推荐分发那两条仍只排队，
    # 写 UI 的那一步分别留在 `RoomNameManager` / `RecommendationManager`，
    # #392-#393 再迁过来 —— 因此此刻房名与推荐各有一份旧的待写入状态，
    # 那是刻意的过渡状态，旧那份随下线一起消失。

    def get_topic_status(self) -> Dict:
        """`:topic` 无参数那一支的状态面。

        返回结构与旧 `TopicManager.get_status` 逐字一致（`current_topic` /
        `next_topic` / `remaining_time`），`TopicCommand` 的回复拼装因此不变。
        """
        result = {
            'current_topic': self.current_topic or 'None',
            'next_topic': self.drafts.pending('topic') or 'None',
            'remaining_time': None,
        }
        if self.drafts.has_pending('topic'):
            result['remaining_time'] = self.drafts.remaining_minutes('topic')
        return result

    def set_topic(self, topic: str) -> Dict:
        """安排房间话题变更。

        与 `TopicManager.change_topic` 的返回文案逐字一致，config.yaml 的话题
        响应模板 `"{topic}"` 因此不必改。切前台的动作保留在这里（话题这一条
        原本就在 manager 里做，标题/主题/公告那几条在命令里做）。真正写 UI 是
        `update_topic` 的事 —— 冷却中的话题要等下一次心跳。
        """
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}

        self.logger.info("Switched to Soul app")

        # 清理话题文本: 支持半角和全角竖线及括号
        new_topic = clean_banner_text(topic, TOPIC_MAX_LENGTH)
        self.drafts.set_pending('topic', new_topic)

        if self.drafts.can_apply_now('topic'):
            self.logger.info(f'Topic will be updated to {new_topic} soon')
            return {'topic': f'{new_topic}. Topic will update soon'}

        remaining_minutes = self.drafts.remaining_minutes('topic')
        self.logger.info(f'Topic will be updated to {new_topic} in {remaining_minutes} minutes')
        return {'topic': f'{new_topic}. Topic will update in {remaining_minutes} minutes'}

    def update_topic(self) -> Dict:
        """心跳：冷却到期且有排队话题时，把它写进黑板。

        两条提前返回都不打日志 —— 这是被 `:topic` 的定时轮询反复走到的分支，
        按 CLAUDE.md 的日志铁律，刷屏属于缺陷而不是信息。

        Returns:
            `{'skipped': 'no_pending_topic'}` / `{'skipped': 'cooldown'}` /
            写 UI 的结果 dict。
        """
        topic = self.drafts.pending('topic')
        if not topic:
            return {'skipped': 'no_pending_topic'}

        if not self.drafts.can_apply_now('topic'):
            return {'skipped': 'cooldown'}

        self.logger.info(f'Attempting to update topic to {topic}')

        # 无论成功失败都推进冷却时钟，避免反复重试。话题这条路线的 UI 调用
        # 可能抛异常，因此「先推进再调用」—— 与旧 TopicManager 同一个次序。
        self.drafts.mark_attempted('topic')

        result = self._write_topic_in_drawer(topic)

        if 'error' not in result:
            # 成功：清空排队的话题
            self.current_topic = topic
            self.drafts.clear('topic')
            self.logger.info(f'Topic updated successfully to: {self.current_topic}')
            self._announce_topic(self.current_topic)
        else:
            # 失败：保留排队的话题，等下一次冷却到期后重试
            self.logger.warning(
                f'Failed to update topic: {result.get("error")}. '
                f'Will retry in {self.drafts.cooldown_minutes("topic")} minute(s).'
            )

        return result

    def _write_topic_in_drawer(self, topic: str) -> Dict:
        """把话题写进黑板：抽屉会话由 `with_window_open` 独占。

        与旧 `TopicManager._update_topic_ui` 相比只改一件事：收尾不再盲按
        `press_back()`。旧实现在成功、失败、风险提示三条路上分别连按 3 / 2 / 3
        次返回键；按多了会直接退出派对房间（spec 用户故事 #12）。现在统一由
        `with_window_open` 的 `finally` 走 `ensure_closed()` 阶梯：自己没有打开
        抽屉就一次都不按；自己打开的就先点遮罩关；只有遮罩关不掉才退化为一次
        保底返回键。

        Returns:
            `{'success': True, 'topic': topic}`，或带 `error` 的 dict。异常一律
            转成 error dict —— 走 `update_topic` 的失败分支保留草稿重试。
        """
        try:
            if RoomState.in_guest_room():
                self.logger.info("In guest room, skip topic UI update")
                return {'skipped': 'guest_room'}

            with self.with_window_open(
                TOPIC_ENTRY_KEYS, 'Failed to find room topic'
            ) as open_error:
                if open_error:
                    return open_error

                driver = self._require_driver()

                # 黑板/抽屉里的「自定义话题」入口（两种皮肤）
                entry_key = driver.wait_for_any(TOPIC_EDIT_ENTRY_KEYS, timeout=5)
                if entry_key is None:
                    return {'error': 'Failed to find edit topic entry'}
                driver.click_element(entry_key)

                # 输入新话题
                if not driver.replace_text('edit_topic_input', topic):
                    return {'error': 'Failed to find topic input'}

                # 点击确认
                if not driver.click_element('edit_topic_confirm'):
                    return {'error': 'Failed to find confirm button'}

                # 等待提交落地
                if self.topic_settle_seconds:
                    time.sleep(self.topic_settle_seconds)

                probe = driver.wait_for_any(TOPIC_SUBMIT_PROBE_KEYS)
                if probe == 'edit_topic_confirm':
                    self.logger.warning('Update topic too frequently, hide edit topic dialog')
                    return {'error': 'update topic too frequently'}
                if probe == 'input_box_entry':
                    self.logger.info(f'Topic updated successfully to: {topic}')
                else:
                    self.logger.warning(f'Unknown key: {probe}')

                return {'success': True, 'topic': topic}

        except Exception:
            self.logger.error(f"Error changing topic: {traceback.format_exc()}")
            return {'error': f'Failed to update topic: {topic}'}

    def _announce_topic(self, topic: str) -> None:
        """写成功后往公屏发一条，与旧 `TopicManager.update` 同一句话。"""
        try:
            from ushareiplay.core.message_dispatch import MessageDispatch

            if not MessageDispatch.is_initialized():
                return
            MessageDispatch.instance().bind_handler(self.handler).send_screen_message(
                f"Updating topic to {topic}"
            )
        except Exception as e:
            self.logger.warning(f"Failed to announce topic update: {e}")

    def set_notice(self, notice: str) -> Dict:
        """安排派对公告变更。

        与话题那条纵切同形：**这里只排队，不碰 UI**。真正写 UI 是 `update_notice`
        的事 —— 冷却中的公告要等下一次心跳。返回文案与旧
        `NoticeManager.set_notice_with_cooldown` 的冷却分支逐字一致，因此
        config.yaml 的公告响应模板不需要改。
        """
        if RoomState.in_guest_room():
            self.logger.info("Skipping notice update in guest room")
            return {'skipped': True, 'reason': 'guest_room'}

        self.drafts.set_pending('notice', notice)

        if not self.drafts.can_apply_now('notice'):
            remaining_minutes = self.drafts.remaining_minutes('notice')
            self.logger.info(
                f"Notice update in cooldown, {remaining_minutes} minutes remaining."
                f" Notice will be set: {notice}"
            )
            return {
                'cooldown': True,
                'remaining_minutes': remaining_minutes,
                'pending_notice': notice,
                'message': f'Notice will be updated in {remaining_minutes} minutes',
            }

        self.logger.info(f'Notice will be updated to {notice} soon')
        return {
            'success': True,
            'notice': notice,
            'message': 'Notice will be updated soon',
        }

    def update_notice(self) -> Dict:
        """心跳：冷却到期且有排队公告时，把它写进房间信息抽屉。

        两条提前返回都不打日志 —— 这是被 `:notice` 的定时轮询反复走到的分支，
        按 CLAUDE.md 的日志铁律，刷屏属于缺陷而不是信息。

        `skipped`（别人房间）**不是**一次失败的尝试：那个房间里一个点击都没发生，
        因此既不清草稿也不推进冷却时钟，也不往公屏播报。写成「跳过之后照样
        `mark_attempted`」会让一条用户明确要求的公告静静排队 15 分钟，
        甚至往公屏播报一条没发生过的变更。

        Returns:
            `{'skipped': 'no_pending_notice'}` / `{'skipped': 'cooldown'}` /
            写 UI 的结果 dict。
        """
        notice = self.drafts.pending('notice')
        if not notice:
            return {'skipped': 'no_pending_notice'}

        if not self.drafts.can_apply_now('notice'):
            return {'skipped': 'cooldown'}

        self.logger.info(f'Attempting to set notice to: {notice}')
        result = self._write_notice_in_drawer(notice)

        if 'skipped' in result:
            # 没写就别记账：草稿留着、预算留着，等真的能写的那一轮再算。
            return result

        # UI 调用自己把异常收敛成 {'error': ...}，因此「先写再推进」—— 与旧
        # NoticeManager 同一个次序（`PendingWrite` 的两种合法次序之一）。
        self.drafts.mark_attempted('notice')

        if 'success' in result:
            self.drafts.clear('notice')
            self.logger.info(f'Notice set successfully: {notice}')
            self._announce_notice(notice)
        else:
            # 失败：保留排队的公告，等下一次冷却到期后重试
            self.logger.warning(
                f'Failed to set notice: {result.get("error", "Unknown error")}. '
                f'Will retry in {self.drafts.cooldown_minutes("notice")} minute(s).'
            )

        return result

    def restore_notice(self, notice: str) -> Dict:
        """房名变更把公告冲掉之后的恢复（用户故事 #6）。

        与 `set_notice` 的差别只有一条：这里**当场写**，因为调用方（房名流程）
        手上正开着抽屉，且必须在这次房名写入结束之前把公告补回去。预算被占用
        时的行为与 `set_notice` 一致：排队，等冷却到期由 `update_notice` 写。

        别人房间里返回 `skipped` 且不推进时钟 —— 同 `update_notice` 的理由。
        """
        if RoomState.in_guest_room():
            self.logger.info("Skipping notice restore in guest room")
            return {'skipped': True, 'reason': 'guest_room'}

        if not self.drafts.can_apply_now('notice'):
            self.drafts.set_pending('notice', notice)
            remaining_minutes = self.drafts.remaining_minutes('notice')
            self.logger.info(
                f"Notice restore in cooldown, {remaining_minutes} minutes remaining."
                f" Notice will be set: {notice}"
            )
            return {
                'cooldown': True,
                'remaining_minutes': remaining_minutes,
                'pending_notice': notice,
                'message': f'Notice will be updated in {remaining_minutes} minutes',
            }

        self.logger.info(f'Restoring notice to: {notice}')
        result = self._write_notice_in_drawer(notice)

        if 'skipped' in result:
            return result

        self.drafts.mark_attempted('notice')

        if 'success' in result:
            self.drafts.clear('notice')
            self.logger.info(f'Notice restored successfully: {notice}')
        else:
            self.drafts.set_pending('notice', notice)
            self.logger.warning(
                f'Failed to restore notice: {result.get("error", "Unknown error")}. '
                f'Will retry in {self.drafts.cooldown_minutes("notice")} minute(s).'
            )

        return result

    def _write_notice_in_drawer(self, notice: str) -> Dict:
        """把公告写进抽屉：公告入口 -> 自定义 -> 输入 -> 提交 -> 收起公告层。

        整段复用端口已有的原语（点元素 / 等任意元素 / 写输入框），没有为公告
        增加任何新原语。抽屉本身的开关归 `with_window_open`：窗口是它打开的就
        由它关，外层开着的就原样留着。

        Returns:
            `{'success': f'Notice restored to: {notice}'}`，带 `error` 的 dict，
            或 `{'skipped': True, 'reason': 'guest_room'}`。异常一律转成 error
            dict —— 走 `update_notice` / `restore_notice` 的失败分支保留草稿重试。
        """
        try:
            if RoomState.in_guest_room():
                self.logger.info("Skipping notice update in guest room")
                return {'skipped': True, 'reason': 'guest_room'}

            self.logger.info(f"准备设置notice: {notice}")

            # 公告原先走的是抽屉默认入口（chat_room_title -> room_topic），保持不变。
            with self.with_window_open() as open_error:
                if open_error:
                    return open_error

                driver = self._require_driver()

                if not driver.click_element(NOTICE_EDIT_ENTRY_KEY):
                    return {'error': 'Failed to find edit notice entry'}
                self.logger.info("点击了编辑notice入口")

                # 公告编辑层弹出后一定有「关闭公告」按钮；没有说明弹的不是这一层。
                if driver.wait_for_any([NOTICE_CLOSE_KEY]) is None:
                    return {'error': 'Close notice not found'}

                customize = driver.wait_for_any(NOTICE_CUSTOMIZE_ENTRY_KEYS)
                if customize is None:
                    # 底部抽屉挡住了「自定义」：先把公告层点掉，不能留在屏幕上。
                    driver.click_element(NOTICE_CLOSE_KEY)
                    self.logger.warning(
                        'Bottom drawer is open, notice customization is disabled, hiding...'
                    )
                    return {'error': 'Failed to find customize notice button'}
                driver.click_element(customize)
                self.logger.info(f"点击了自定义按钮 {customize}")

                if not driver.replace_text(NOTICE_INPUT_KEY, notice):
                    return {'error': 'Failed to find notice input'}
                self.logger.info(f"输入了notice内容: {notice}")

                if not driver.click_element(NOTICE_CONFIRM_KEY):
                    return {'error': 'Failed to find confirm button'}
                self.logger.info("点击了确认按钮")

                # 收起公告编辑层（抽屉本身由 with_window_open 收尾）
                driver.click_element(NOTICE_CLOSE_KEY)
                self.logger.info("隐藏notice设置对话框")

            self.logger.info(f"成功设置notice: {notice}")
            return {'success': f'Notice restored to: {notice}'}

        except Exception:
            self.logger.error(f"设置notice时出错: {traceback.format_exc()}")
            return {'error': f'Failed to update notice to {notice}'}

    def _announce_notice(self, notice: str) -> None:
        """写成功后往公屏发一条，与旧 `NoticeCommand.update` 同一句话。"""
        try:
            from ushareiplay.core.message_dispatch import MessageDispatch

            if not MessageDispatch.is_initialized():
                return
            MessageDispatch.instance().bind_handler(self.handler).send_screen_message(
                f'Notice updated to: {notice}'
            )
        except Exception as e:
            self.logger.warning(f'Failed to announce notice update: {e}')

    async def set_default_notice(self) -> Dict:
        """开房之后把配置里的默认公告排进去。

        与旧 `NoticeManager.set_default_notice` 同一个返回面（`success` /
        `cooldown` / `skipped` / `error`），因此 `PartyManager` 那句
        「默认notice设置成功」不需要改。写入同样走草稿库：15 分钟预算被用户
        的 `:notice` 占着时，默认公告排队而不是覆盖它。
        """
        try:
            default_notice = (getattr(self.handler, 'config', None) or {}).get(
                'default_notice'
            )
            if not default_notice:
                self.logger.warning("未找到default_notice配置")
                return {'error': 'No default_notice configuration found'}

            self.logger.info(f"准备设置默认notice: {default_notice}")

            # 等待界面稳定
            await asyncio.sleep(3)

            result = self.set_notice(default_notice)
            if 'success' in result:
                self.logger.info(f"成功设置默认notice: {default_notice}")
            else:
                self.logger.warning(
                    f"设置默认notice失败: {result.get('error', 'Unknown error')}"
                )

            return result

        except Exception as e:
            self.logger.error(f"设置默认notice时出错: {traceback.format_exc()}")
            return {'error': f'Failed to set default notice: {str(e)}'}

    def get_system_default_notices(self) -> List[str]:
        """系统默认公告文案：房间公告里出现这些内容说明被系统重置了。"""
        cfg = getattr(self.handler, 'config', None)
        if not cfg:
            return list(SYSTEM_DEFAULT_NOTICES_FALLBACK)
        if 'system_default_notices' in cfg:
            return cfg.get('system_default_notices', [])
        if 'soul' in cfg and isinstance(cfg['soul'], dict):
            return cfg['soul'].get('system_default_notices', [])
        return list(SYSTEM_DEFAULT_NOTICES_FALLBACK)

    def get_default_notice(self) -> str:
        """默认公告文案，被系统重置后恢复成它。"""
        cfg = getattr(self.handler, 'config', None)
        if not cfg:
            return DEFAULT_NOTICE_FALLBACK
        if 'default_notice' in cfg:
            return cfg.get('default_notice', DEFAULT_NOTICE_FALLBACK)
        if 'soul' in cfg and isinstance(cfg['soul'], dict):
            return cfg['soul'].get('default_notice', DEFAULT_NOTICE_FALLBACK)
        return DEFAULT_NOTICE_FALLBACK

    def _read_notice_text_from_ui(self) -> str:
        """读一次抽屉里当前公告的文案。

        抽屉端口只建模物理动作（探测 / 点 / 等 / 写），不承载「读文本」；这一次
        读只用于**判定**公告是不是被系统冲掉了，因此这里仍然直接问 handler 的
        element_finder，与旧 `NoticeManager.get_notice_text_from_ui` 逐字一致
        （用 `chat_room_notice` 而不是 `edit_notice_entry`，避免把「编辑」当成文案）。
        """
        finder = getattr(self.handler, 'element_finder', None)
        if finder is None:
            return ""
        element = finder.try_find_element(NOTICE_TEXT_KEY, log=False)
        if element:
            text = (finder.get_element_text(element) or "").strip()
            if text and text != "编辑":
                return text
        return ""

    def _audit_notice_in_open_window(self) -> Dict:
        """窗口已开着时的公告核对：被系统重置就就地恢复默认公告。

        抽屉由外层（全量审计）打开，本方法只在自己的会话里编辑那一行 —— 因此
        「核对并修正」与房名/话题的纠正发生在同一次抽屉会话内。
        """
        try:
            driver = self.drawer_driver
            if driver is None:
                return {'skipped': 'not_initialized'}

            # 等待 edit_notice_entry 呈现（支持在前一步刚执行过房间类型切换后的界面过渡）
            if driver.wait_for_any([NOTICE_EDIT_ENTRY_KEY], timeout=2) is None:
                return {'skipped': 'edit_notice_entry not visible'}

            current_text = self._read_notice_text_from_ui()
            # 没有行为触发的探测，按日志铁律只留在 DEBUG。
            self.logger.debug(f"Inspected room notice text from UI: '{current_text}'")

            system_notices = self.get_system_default_notices()

            is_reset = not current_text or any(
                system_notice in current_text for system_notice in system_notices
            )

            if not is_reset:
                return {'status': 'notice_normal', 'current_text': current_text}

            default_notice = self.get_default_notice()
            self.logger.info(
                f"Notice reset detected in dialog ('{current_text}'), "
                f"restoring default notice: {default_notice}"
            )

            driver.click_element(NOTICE_EDIT_ENTRY_KEY)
            self.logger.info("Clicked edit_notice_entry in room info window")

            if driver.wait_for_any([NOTICE_CLOSE_KEY], timeout=3) is None:
                return {'error': 'close_notice not found'}

            customize = driver.wait_for_any(NOTICE_CUSTOMIZE_ENTRY_KEYS, timeout=3)
            if customize is None:
                driver.click_element(NOTICE_CLOSE_KEY)
                self.logger.warning('Bottom drawer is open, notice customization is disabled')
                return {'error': 'Failed to find customize notice button'}

            driver.click_element(customize)

            if not driver.replace_text(NOTICE_INPUT_KEY, default_notice, timeout=3):
                return {'error': 'Failed to find notice input'}

            driver.click_element(NOTICE_CONFIRM_KEY, timeout=3)
            driver.click_element(NOTICE_CLOSE_KEY, timeout=3)

            self.drafts.mark_attempted('notice')
            self.drafts.clear('notice')
            self.logger.info(
                f"Successfully restored notice in room info window to: {default_notice}"
            )
            return {'success': True, 'restored_notice': default_notice}
        except Exception:
            self.logger.error(f"Error in _audit_notice_in_open_window: {traceback.format_exc()}")
            return {'error': str(traceback.format_exc())}

    def set_title(self, title: str, theme: Optional[str] = None) -> Dict:
        """安排房间标题变更；`theme` 给了就一起改主题。

        返回文案与 `RoomNameManager.set_next_title` 逐字一致（config.yaml 的
        标题响应模板是 `"{title}"`）。主题非法时直接返回主题的错误，且不排队标题
        —— 与既有实现同一个次序。
        """
        if RoomState.in_guest_room():
            self.logger.info("Skipping set_next_title in guest room")
            return {'skipped': True, 'reason': 'guest_room'}

        if theme:
            theme_result = self.set_theme(theme)
            if 'error' in theme_result:
                return theme_result

        new_title = clean_banner_text(title, TITLE_MAX_LENGTH)
        self.drafts.set_pending('title', new_title)

        if not self.drafts.can_apply_now('title'):
            remaining_minutes = self.drafts.remaining_minutes('title')
            self.logger.info(f'Title will be updated to {new_title} in {remaining_minutes} minutes')
            return {'title': f'{new_title}. Title will update in {remaining_minutes} minutes'}

        self.logger.info(f'Title will be updated to {new_title} soon')
        return {'title': f'{new_title}. Title will update soon'}

    def set_theme(self, theme: str) -> Dict:
        """校验并记录一个待生效的主题。

        主题不单独占冷却预算：它只是房名草稿的前缀（ADR-0001 的共享冷却）。
        校验规则与 `RoomNameManager.set_theme` 逐字一致。
        """
        if RoomState.in_guest_room():
            return {'error': '他人房间模式下不可修改房间主题'}

        if len(theme) > 2:
            return {'error': '主题最多两个字符'}

        new_theme = theme.strip()
        if not new_theme:
            return {'error': '主题不能为空'}

        old_theme = self.drafts.pending_theme()
        if old_theme != new_theme:
            self.drafts.set_pending_theme(new_theme)
            self.logger.info(f'Theme updated from {old_theme} to {new_theme}, pending UI update')
        else:
            self.logger.info(f'Theme unchanged: {new_theme}')

        return {
            'success': True,
            'theme': new_theme,
            'old_theme': old_theme,
        }

    def compose_room_title(self, title: Optional[str] = None) -> str:
        """把草稿合成房间名 `{theme}｜{title}`（ADR-0001 不变量）。"""
        return self.drafts.compose_room_title(title)

    def parse_room_title(self, room_title_text: str):
        """从 UI 读到的房间名里拆出 `(主题, 标题)`；没有分隔符则 None。"""
        return self.drafts.parse_room_title(room_title_text)

    def set_recommendation(self, enabled: bool) -> Dict:
        """在抽屉里切换推荐分发。

        抽屉的打开与关闭由本方法独占（原先 `commands/recommend.py` 自己开窗、
        自己 `close_with_back`，是第五份打开副本）。推荐分发没有冷却，是一次
        开关，因此不走草稿库；点选项的真实 Appium 逻辑仍在
        `RecommendationManager` 里，#393 把它迁进来。

        选项层盖在抽屉之上，所以先 `close_with_back()` 收掉选项层，退出上下文
        时再由 `ensure_closed()` 统一确认抽屉已经关好。
        """
        with self.with_window_open() as open_error:
            if open_error:
                return open_error

            # 懒加载：避免与 RecommendationManager 的循环依赖（RecommendationManager 依赖房间信息抽屉）
            from ushareiplay.managers.recommendation_manager import RecommendationManager
            if not RecommendationManager.is_initialized():
                return {'skipped': True, 'reason': 'not_initialized'}

            result = RecommendationManager.instance().update_recommendation_ui(enabled)
            self.close_with_back()
            return result

    # ------------------------------------------------------------------
    # 窗口内的顺序：先纠偏，再编辑
    # ------------------------------------------------------------------

    def _sync_recommendation(self, wait: bool = False) -> Dict:
        """读取真实推荐分发状态并纠正 RoomState 中的记录。

        Args:
            wait: 是否等状态字段渲染出来。只有「窗口刚被自己打开、紧接着就要
                一次性改完所有字段」的全量审计才等；标题更新等被动路径沿用
                原来的非阻塞读 —— 布局里没有该字段时，等待会白等满整个超时。
        """
        # 懒加载：避免与 RecommendationManager 的循环依赖（RecommendationManager 依赖房间信息抽屉）
        from ushareiplay.managers.recommendation_manager import RecommendationManager
        if not RecommendationManager.is_initialized():
            return {'skipped': True, 'reason': 'not_initialized'}
        rec_mgr = RecommendationManager.instance()
        ui_status = rec_mgr.inspect_current_ui_status(wait=wait)
        if ui_status is not None:
            rec_mgr.room_state.recommendation_enabled = ui_status
        return {'success': True, 'status': ui_status}

    def _sync_room_type(self) -> Dict:
        """派对类型检查与修正（"闲聊唠嗑" -> "唱歌听歌"）。"""
        # 懒加载：避免与 PartyManager 的循环依赖（PartyManager 依赖房间信息抽屉）
        from ushareiplay.managers.party_manager import PartyManager
        if not PartyManager.is_initialized() or getattr(PartyManager.instance(), 'handler', None) is None:
            return {'skipped': True, 'reason': 'not_initialized'}
        return PartyManager.instance().sync_and_correct_room_type_if_dialog_open()

    def sync_while_open(self, wait: bool = False) -> Dict:
        """窗口已打开时的「先纠偏再编辑」顺序。

        推荐分发状态与派对类型必须在任何字段编辑之前同步：编辑层（标题/话题/
        公告）会改变抽屉内容，之后再读这两个状态已经不反映进入窗口时的真实值。
        这个顺序原先只写在 `RoomNameManager._update_title_ui` 的方法体里，
        现在由本模块拥有，`audit_and_repair()` 复用同一步骤。

        Args:
            wait: 是否等推荐状态字段渲染出来。被动路径（标题更新时窗口已开着）
                保持原来的非阻塞读；`audit_and_repair()` 自己刚打开窗口，传 True。
        """
        results: Dict = {}
        for key, step in (
            ('recommendation', lambda: self._sync_recommendation(wait)),
            ('room_type', self._sync_room_type),
        ):
            try:
                results[key] = step()
            except Exception as e:
                self.logger.warning(f"Room info window: error in {key} sync: {e}")
        return results

    # ------------------------------------------------------------------
    # 窗口内的全量审计
    # ------------------------------------------------------------------

    def audit_and_repair(self) -> Dict:
        """打开窗口，一次性顺序完成四类检查与修正，最后统一关窗。

        在所有修正尝试完成之前绝不提前关窗。任何一项修正失败都会标记
        `pending_audit_retry`，供 `process_pending_retry()` 补救。
        """
        if RoomState.in_guest_room():
            return {'skipped': True, 'reason': 'guest_room'}

        results: Dict = {}
        with self.with_window_open() as open_error:
            if open_error:
                self.pending_audit_retry = True
                self.last_audit_results = {'open': open_error}
                return {'open': open_error}

            # 1-2. 先纠偏（推荐分发状态、派对类型），顺序由 sync_while_open 拥有。
            # 窗口是这里刚打开的，字段可能还没渲染 —— 全量审计等它出现。
            results.update(self.sync_while_open(wait=True))

            # 3. 房间标题/主题检查与同步（懒加载：避免与 RoomNameManager 的顶层模块循环依赖）
            try:
                from ushareiplay.managers.room_name_manager import RoomNameManager
                if RoomNameManager.is_initialized() and getattr(RoomNameManager.instance(), 'handler', None) is not None:
                    results['room_name'] = RoomNameManager.instance().initialize_from_ui()
            except Exception as e:
                self.logger.warning(f"Auditor: error in room name sync: {e}")

            # 4. 派对公告检查与修正：本模块自己的字段，直接在同一次会话里核对。
            #    只在「编辑入口真的在屏幕上」时才有行为可做，其余一律静默跳过。
            try:
                results['notice'] = self._audit_notice_in_open_window()
            except Exception as e:
                self.logger.warning(f"Auditor: error in notice sync: {e}")

        has_failure = any(
            isinstance(v, dict) and ('error' in v or v.get('success') is False)
            for v in results.values()
        )
        self.pending_audit_retry = has_failure
        self.last_audit_results = results

        if has_failure:
            self.logger.warning(f"Room info audit completed with pending retries: {results}")
        else:
            self.logger.info(f"Room info audit completed successfully in open window: {results}")

        return results

    def process_pending_retry(self) -> Dict:
        """补救机制：上次审计有未完成项时，重新打开窗口执行一次全量修正。

        注意：截至本次重构，生产代码里没有任何调用点触发它（原先的「供定时器/
        循环重试」从未接线）。保留是为了不静默丢掉这套补救语义；接线与否需要
        单独决定。
        """
        if RoomState.in_guest_room():
            return {'skipped': 'guest_room'}

        if not self.pending_audit_retry:
            return {'skipped': 'No pending audit retry'}

        self.logger.info("Triggering pending room info audit retry via timer/update loop")
        try:
            return self.audit_and_repair()
        except Exception as e:
            self.logger.error(f"Error in process_pending_retry: {traceback.format_exc()}")
            return {'error': str(e)}
