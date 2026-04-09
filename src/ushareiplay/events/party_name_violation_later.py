"""
派对名违规等弹窗：检测到「稍后再说」时先关闭弹窗，并将房间标题排队为「日推」。
"""

__event__ = "PartyNameViolationLaterEvent"
__elements__ = ["party_name_violation_later"]

from ushareiplay.core.base_event import BaseEvent


class PartyNameViolationLaterEvent(BaseEvent):
    async def handle(self, key: str, element_wrapper):
        try:
            element = self.handler.wait_for_element_clickable_plus("party_name_violation_later")
            if not element:
                self.logger.warning("party_name_violation_later present in page_source but not clickable")
                return False
            element.click()
            self.logger.info("Clicked party_name_violation_later (稍后再说)")

            from ushareiplay.managers.title_manager import TitleManager

            TitleManager.instance().set_next_title("日推")
            return True
        except Exception as e:
            self.logger.error(f"PartyNameViolationLaterEvent: {e}")
            return False
