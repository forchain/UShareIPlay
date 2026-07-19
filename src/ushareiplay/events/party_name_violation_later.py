"""
派对名违规弹窗：关闭「稍后再说」，仅在快照明确证明名称违规时重设房名。
"""

__event__ = "PartyNameViolationLaterEvent"
__elements__ = ["party_name_violation_later"]

from ushareiplay.core.base_event import BaseEvent


class PartyNameViolationLaterEvent(BaseEvent):
    _NAME_MARKERS = ("派对名", "派对名称", "房间名", "房间名称")
    _VIOLATION_MARKERS = ("违规", "不符合规范", "审核")

    @classmethod
    def _is_party_name_violation(cls, element_wrapper) -> bool:
        context = element_wrapper.context_text() if element_wrapper else ""
        return any(marker in context for marker in cls._NAME_MARKERS) and any(
            marker in context for marker in cls._VIOLATION_MARKERS
        )

    async def handle(self, key: str, element_wrapper):
        try:
            element = self.handler.element_finder.wait_for_element_clickable("party_name_violation_later")
            if not element:
                self.logger.warning("party_name_violation_later present in page_source but not clickable")
                return False
            element.click()
            self.logger.info("Clicked party_name_violation_later (稍后再说)")

            if not self._is_party_name_violation(element_wrapper):
                self.logger.info("Skipped title reset: tvLater snapshot has no party-name violation evidence")
                return True

            from ushareiplay.managers.title_manager import TitleManager

            TitleManager.instance().set_next_title("日推")
            return True
        except Exception as e:
            self.logger.error(f"PartyNameViolationLaterEvent: {e}")
            return False
