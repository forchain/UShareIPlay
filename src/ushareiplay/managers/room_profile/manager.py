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
async 会打断三个同步调用点（`room_name_manager` / `notice_manager` /
`party_manager`），因此不做。
"""

import logging
import traceback
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Sequence

from ushareiplay.core.singleton import Singleton
from ushareiplay.helpers.room_banner import TOPIC_MAX_LENGTH, TITLE_MAX_LENGTH, clean_banner_text
from ushareiplay.managers.room_profile.drafts import ProfileDraftStore
from ushareiplay.managers.room_profile.driver import (
    DEFAULT_ENTRY_KEYS,
    RoomProfileDrawerDriverPort,
)
from ushareiplay.state.room_state import RoomState


class RoomProfileManager(Singleton):
    """打开、检测、关闭房间信息抽屉，并拥有窗口内的全量审计顺序。"""

    def __init__(self, handler=None, drawer_driver: Optional[RoomProfileDrawerDriverPort] = None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._drawer_driver = drawer_driver
        self._drafts = ProfileDraftStore()
        self.pending_audit_retry = False
        self.last_audit_results: Dict = {}

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
    def with_window_open(self, entry_keys: Optional[Sequence[str]] = None) -> Iterator[Optional[dict]]:
        """窗口开着的上下文：需要时才打开，且只关掉自己打开的那一次。

        Yields:
            error dict（打开失败）或 None（窗口可用、可以开始编辑）。
            打开失败时不会 yield 一个「假装开着」的窗口，调用方据此提前返回。
        """
        if self.is_open():
            yield None
            return

        open_error = self.ensure_open(entry_keys)
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
    # 字段草稿：只排队，不碰 UI
    # ------------------------------------------------------------------
    #
    # 这一节是 #388 建立的统一面。写 UI 的那一步仍留在既有的 TopicManager /
    # NoticeManager / RoomNameManager 里 —— #390-#393 才把它们迁过来。因此
    # 此刻同一字段存在两份 PendingWrite（一份在这份草稿库里，一份在旧 manager
    # 上），这是刻意的过渡状态，不是重复实现：旧那份随下线一起消失。

    def set_topic(self, topic: str) -> Dict:
        """安排房间话题变更。

        与 `TopicManager.change_topic` 的返回文案逐字一致，config.yaml 的话题
        响应模板 `"{topic}"` 因此不必改。切前台的动作保留在原处（话题这一条
        原本就在 manager 里做，标题/主题/公告那几条在命令里做）。
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

    def set_notice(self, notice: str) -> Dict:
        """安排派对公告变更。

        冷却中的返回结构与 `NoticeManager.set_notice_with_cooldown` 逐字一致；
        冷却外那次「立刻写 UI」留在旧 manager（#392 迁过来）。
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

            # 4. 派对公告检查与修正（懒加载：避免与 NoticeManager 的顶层模块循环依赖）
            try:
                from ushareiplay.managers.notice_manager import NoticeManager
                if NoticeManager.is_initialized() and getattr(NoticeManager.instance(), 'handler', None) is not None:
                    results['notice'] = NoticeManager.instance().sync_and_correct_notice_if_dialog_open()
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
