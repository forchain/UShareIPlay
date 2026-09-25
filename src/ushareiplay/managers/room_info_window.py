"""房间信息窗口（房间标题所在的抽屉）的唯一所有者。

同一个抽屉承载四类字段：房间标题、房间话题、派对公告、派对类型与推荐分发。
原先它有四个「打开者」各自复制一遍打开 ritual，关闭则靠 `PartyManager` 的
`finally` 兜底，而「在窗口里必须按什么顺序同步」只写在注释里。

现在只有一个模块知道窗口什么时候开着：

    with RoomInfoWindow.instance().with_window_open() as open_error:
        if open_error:
            return open_error
        <每个 manager 只做自己字段的编辑>

    results = RoomInfoWindow.instance().audit_and_repair()   # 一次性全量检查与修正

`with_window_open()` 只在「窗口是它打开的」时候负责关窗；窗口本来就开着时
（例如被外层流程打开），退出后保持原状，让外层决定何时关。

`RoomInfoWindowAuditor` 的职责（全量审计 + 待重试标记）已并入本模块的
`audit_and_repair()` / `process_pending_retry()`，该模块已删除。
"""

import traceback
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Sequence

from ushareiplay.core.singleton import Singleton

# 窗口开着的证据：抽屉自身，或抽屉内任一控件。
DIALOG_KEYS = (
    'party_room_type_option',
    'party_recommendation_status',
    'edit_topic_entry',
    'edit_notice_entry',
    'slide_drawer',
)

# 打开抽屉的入口。chat_room_title 是既有调用点里最常用的入口，
# room_topic 指向同一个抽屉，作为兜底。
DEFAULT_ENTRY_KEYS = ('chat_room_title', 'room_topic')


class RoomInfoWindow(Singleton):
    """打开、检测、关闭房间信息窗口，并拥有窗口内的全量审计顺序。"""

    def __init__(self):
        self._handler = None
        self._logger = None
        self.pending_audit_retry = False
        self.last_audit_results: Dict = {}

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            if SoulHandler.is_initialized():
                self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            if self.handler is not None and getattr(self.handler, 'logger', None) is not None:
                self._logger = self.handler.logger
            else:
                import logging
                self._logger = logging.getLogger("RoomInfoWindow")
        return self._logger

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """窗口（抽屉）当前是否开着。"""
        handler = self.handler
        if handler is None:
            return False
        for key in DIALOG_KEYS:
            if handler.element_finder.try_find_element(key, log=False):
                return True
        return False

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

        handler = self.handler
        if handler is None:
            return {'error': error_message or 'Soul handler is not available'}

        for entry_key in entry_keys or DEFAULT_ENTRY_KEYS:
            result = handler.ui_actions.switch_and_click(
                entry_key,
                error_message=error_message or f'Failed to open room info window via {entry_key}',
            )
            if not (isinstance(result, dict) and "error" in result):
                return None
            self.logger.warning(f"Room info window entry '{entry_key}' failed, trying next entry")

        return {'error': error_message or 'Failed to open room info window'}

    def ensure_closed(self) -> None:
        """确保窗口已关闭，恢复至主房间界面。

        优先使用 UI 正规关窗操作（close_drawer('slide_drawer')）；仅在抽屉关窗未
        成功且弹窗标志依然存留时，才使用 press_back() 作为最后的保底防御，防止因
        过快盲按 press_back() 导致误退出派对房间。
        """
        try:
            if not self.is_open():
                return

            self.logger.info("Room info window is open, attempting to close via close_drawer UI action")
            from ushareiplay.managers.recovery_manager import RecoveryManager
            if RecoveryManager.is_initialized():
                if RecoveryManager.instance().close_drawer('slide_drawer'):
                    self.logger.info("Successfully closed room info window via close_drawer")
                    return

            self.logger.warning("close_drawer did not close room info window, falling back to press_back")
            self.handler.key_actions.press_back()
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
            self.handler.key_actions.press_back()
            if self.is_open():
                self.logger.info("Room info window still visible after back, pressing back again to exit")
                self.handler.key_actions.press_back()
        except Exception as e:
            self.logger.warning(f"Error closing room info window with back: {e}")

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
        from ushareiplay.state.room_state import RoomState
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

            # 3. 房间标题/主题检查与同步
            try:
                from ushareiplay.managers.room_name_manager import RoomNameManager
                if RoomNameManager.is_initialized() and getattr(RoomNameManager.instance(), 'handler', None) is not None:
                    results['room_name'] = RoomNameManager.instance().initialize_from_ui()
            except Exception as e:
                self.logger.warning(f"Auditor: error in room name sync: {e}")

            # 4. 派对公告检查与修正
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
        from ushareiplay.state.room_state import RoomState
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
