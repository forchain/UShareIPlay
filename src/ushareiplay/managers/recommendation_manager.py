import traceback
from typing import Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.state.room_state import RoomState


class RecommendationManager(Singleton):
    """
    派对推荐管理器
    负责房间推荐状态的读取、更新、主动同步与被动纠偏。
    """

    def __init__(self):
        self._handler = None
        self._logger = None

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler

            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def room_state(self):
        return RoomState.instance()

    def inspect_current_ui_status(self, wait: bool = False) -> Optional[bool]:
        """
        在房间标题弹窗已打开的前提下，检查当前的推荐状态。
        Args:
            wait: 是否等待元素出现（当刚点击打开标题弹窗时建议设为 True）
        Returns:
            True: 显示 "所有人" (开放推荐)
            False: 显示 "关闭推荐分发" (关闭推荐)
            None: 未定位到元素或不匹配
        """
        try:
            if wait:
                elem = self.handler.element_finder.wait_for_element(
                    "party_recommendation_status"
                )
            else:
                elem = self.handler.element_finder.try_find_element(
                    "party_recommendation_status", log=False
                )
            if not elem:
                return None
            text = self.handler.element_finder.get_element_text(elem)
            if not text:
                return None
            text = text.strip()
            if "所有人" in text:
                return True
            if "关闭推荐分发" in text:
                return False
            return None
        except Exception:
            self.logger.error(f"Error inspecting recommendation UI status: {traceback.format_exc()}")
            return None

    def sync_ui_status_if_dialog_open(self) -> Optional[bool]:
        """
        被动纠偏：当标题弹窗因任何原因（如更新标题/主题）被打开时被动调用。
        读取当前真实 UI 状态并同步修正 RoomState 中的记录。
        """
        ui_status = self.inspect_current_ui_status()
        if ui_status is not None:
            current_saved = self.room_state.recommendation_enabled
            if current_saved != ui_status:
                self.logger.info(
                    f"Passive sync detected recommendation status drift: saved={current_saved} -> ui={ui_status}"
                )
                self.room_state.recommendation_enabled = ui_status
        return ui_status

    def update_recommendation_ui(self, target_state: bool) -> dict:
        """
        在标题弹窗已打开的前提下，将推荐状态更新为目标状态 target_state。
        """
        try:
            current_status = self.inspect_current_ui_status()
            if current_status == target_state:
                self.room_state.recommendation_enabled = target_state
                self.logger.info(f"Recommendation status is already target state ({target_state})")
                return {"success": True, "recommendation_enabled": target_state}

            status_elem = self.handler.element_finder.wait_for_element_clickable(
                "party_recommendation_status"
            )
            if not status_elem:
                return {"error": "Failed to find recommendation status entry"}
            status_elem.click()
            self.logger.info("Clicked recommendation status entry")

            opt_key = "party_recommendation_open" if target_state else "party_recommendation_close"
            opt_elem = self.handler.element_finder.wait_for_element_clickable(opt_key)
            if not opt_elem:
                return {"error": f"Failed to find option for recommendation ({opt_key})"}
            opt_elem.click()
            self.logger.info(f"Clicked recommendation option ({opt_key})")

            self.room_state.recommendation_enabled = target_state
            return {"success": True, "recommendation_enabled": target_state}
        except Exception:
            self.logger.error(f"Error updating recommendation UI: {traceback.format_exc()}")
            return {"error": "Error updating recommendation UI"}

    def close_title_dialog(self) -> None:
        """
        关闭房间信息弹窗，确保返回到派对主界面。
        由于切换推荐选项后可能停留在房间信息弹窗（父级对话框），需要确保彻底退出弹窗。
        """
        try:
            self.handler.key_actions.press_back()
            elem = self.handler.element_finder.try_find_element(
                "party_recommendation_status", log=False
            )
            if elem:
                self.logger.info("Room info window still visible after back, pressing back again to exit")
                self.handler.key_actions.press_back()
        except Exception as e:
            self.logger.warning(f"Error closing title dialog: {str(e)}")

    def ensure_synced_on_return(self) -> dict:
        """
        主动同步：回到/恢复房间或执行 info 时调用。
        若 RoomState 已有保存状态，则跳过（不打开弹窗）；
        若状态未保存 (None)，仅打开第 2 层房间信息窗口，读取 tv_private_title 文本保存状态，
        随后按一次返回键退出第二层窗口。不强行点击进入第三层选项列表。
        """
        if self.room_state.recommendation_enabled is not None:
            return {"skipped": True, "reason": "already_saved"}

        try:
            switch_res = self.handler.ui_actions.switch_and_click(
                "chat_room_title", error_message="Failed to click room title for sync"
            )
            if isinstance(switch_res, dict) and "error" in switch_res:
                return switch_res

            ui_status = self.inspect_current_ui_status(wait=True)
            if ui_status is not None:
                self.room_state.recommendation_enabled = ui_status
                self.logger.info(f"Inspected room recommendation status from UI: {ui_status}")

            from ushareiplay.managers.party_manager import PartyManager
            if PartyManager.is_initialized():
                try:
                    PartyManager.instance().sync_and_correct_room_type_if_dialog_open()
                except Exception as e:
                    self.logger.warning(f"Error syncing room type in ensure_synced_on_return: {e}")

            from ushareiplay.managers.notice_manager import NoticeManager
            if NoticeManager.is_initialized():
                try:
                    NoticeManager.instance().sync_and_correct_notice_if_dialog_open()
                except Exception as e:
                    self.logger.warning(f"Error syncing notice in ensure_synced_on_return: {e}")

            from ushareiplay.managers.room_name_manager import RoomNameManager
            if RoomNameManager.is_initialized():
                try:
                    RoomNameManager.instance().initialize_from_ui()
                except Exception as e:
                    self.logger.warning(f"Error initializing room name in ensure_synced_on_return: {e}")

            closed_by_party_mgr = False
            if PartyManager.is_initialized():
                try:
                    PartyManager.instance().ensure_room_info_window_closed()
                    closed_by_party_mgr = True
                except Exception as e:
                    self.logger.warning(f"PartyManager close window failed, falling back to press_back: {e}")

            if not closed_by_party_mgr:
                self.handler.key_actions.press_back()

            self.logger.info("Closed room info window after reading recommendation status and auditing room attributes")
            return {"success": True, "recommendation_enabled": ui_status}
        except Exception:
            self.logger.error(f"Error in ensure_synced_on_return: {traceback.format_exc()}")
            return {"error": "Error during active recommendation sync"}
