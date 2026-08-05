import traceback
from typing import Dict
from ushareiplay.core.singleton import Singleton


class RoomInfoWindowAuditor(Singleton):
    """
    统一房间信息窗口审计与修正管理器 (Room Info Window Auditor).

    核心职责：
    1. 确保在房间信息窗口关闭之前，一次性顺序完成推荐状态、派对类型、房间标题/主题、派对公告的全部检测与修正。
    2. 若审计过程中有任何配置项修正失败或因异常跳过，自动标记 pending_audit_retry，供后续定时器/循环自动重试补救。
    """

    def __init__(self):
        self.pending_audit_retry = False
        self.last_audit_results = {}

    @property
    def handler(self):
        if not hasattr(self, '_handler') or self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            if SoulHandler.is_initialized():
                self._handler = SoulHandler.instance()
            else:
                self._handler = None
        return self._handler

    @property
    def logger(self):
        if not hasattr(self, '_logger') or self._logger is None:
            if self.handler and hasattr(self.handler, 'logger'):
                self._logger = self.handler.logger
            else:
                import logging
                self._logger = logging.getLogger("RoomInfoWindowAuditor")
        return self._logger

    def audit_all_in_open_window(self) -> Dict:
        """
        在已打开的房间信息窗口中，一次性顺序完成所有属性检查与修正。
        在所有修正尝试完成之前，绝对不提前关闭窗口。
        """
        results = {}

        # 1. 推荐分发检查与同步
        try:
            from ushareiplay.managers.recommendation_manager import RecommendationManager
            if RecommendationManager.is_initialized():
                rec_mgr = RecommendationManager.instance()
                ui_status = rec_mgr.inspect_current_ui_status(wait=True)
                if ui_status is not None:
                    rec_mgr.room_state.recommendation_enabled = ui_status
                results['recommendation'] = {'success': True, 'status': ui_status}
        except Exception as e:
            self.logger.warning(f"Auditor: error in recommendation inspect: {e}")

        # 2. 派对类型检查与修正 ("闲聊唠嗑" -> "唱歌听歌")
        try:
            from ushareiplay.managers.party_manager import PartyManager
            if PartyManager.is_initialized() and getattr(PartyManager.instance(), 'handler', None) is not None:
                type_res = PartyManager.instance().sync_and_correct_room_type_if_dialog_open()
                results['room_type'] = type_res
        except Exception as e:
            self.logger.warning(f"Auditor: error in room type sync: {e}")

        # 3. 房间标题/主题检查与同步
        try:
            from ushareiplay.managers.room_name_manager import RoomNameManager
            if RoomNameManager.is_initialized() and getattr(RoomNameManager.instance(), 'handler', None) is not None:
                name_res = RoomNameManager.instance().initialize_from_ui()
                results['room_name'] = name_res
        except Exception as e:
            self.logger.warning(f"Auditor: error in room name sync: {e}")

        # 4. 派对公告检查与修正 (检测系统重置如“弹唱大会”/“Souler们在随便聊聊ing”/“蹲一个人”)
        try:
            from ushareiplay.managers.notice_manager import NoticeManager
            if NoticeManager.is_initialized() and getattr(NoticeManager.instance(), 'handler', None) is not None:
                notice_res = NoticeManager.instance().sync_and_correct_notice_if_dialog_open()
                results['notice'] = notice_res
        except Exception as e:
            self.logger.warning(f"Auditor: error in notice sync: {e}")

        # 判断是否有未完成项
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

    def audit_and_close(self) -> Dict:
        """
        完成全量审计与修正后，统一安全关窗。
        """
        results = self.audit_all_in_open_window()

        # 统一由 Safe Exit Guard 闭环关窗
        try:
            from ushareiplay.managers.party_manager import PartyManager
            if PartyManager.is_initialized():
                PartyManager.instance().ensure_room_info_window_closed()
            elif self.handler and hasattr(self.handler, 'key_actions'):
                self.handler.key_actions.press_back()
        except Exception as e:
            self.logger.warning(f"Auditor: error closing window: {e}")

        return results

    def process_pending_retry() -> Dict:
        """
        定时器/循环补救机制：若之前的审计存在未完成项，主动打开房间信息窗口重新执行一次性修正。
        """
        if not self.pending_audit_retry:
            return {'skipped': 'No pending audit retry'}

        self.logger.info("Triggering pending room info audit retry via timer/update loop")
        try:
            if self.handler and hasattr(self.handler, 'ui_actions'):
                switch_res = self.handler.ui_actions.switch_and_click(
                    "chat_room_title", error_message="Failed to click room title for audit retry"
                )
                if isinstance(switch_res, dict) and "error" in switch_res:
                    return switch_res

            return self.audit_and_close()
        except Exception as e:
            self.logger.error(f"Error in process_pending_retry: {traceback.format_exc()}")
            return {'error': str(e)}
