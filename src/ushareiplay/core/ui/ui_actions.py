class UIActions:
    """Reusable UI action sequences for a single app handler."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def logger(self):
        return self.owner.logger

    def switch_and_click(
            self, element_key: str, *, error_message: str, timeout: int = 10,
            click_kwargs: dict | None = None
    ) -> dict:
        """Switch to this handler's app, wait for an element, then click it."""
        if not self.owner.key_actions.switch_to_app():
            self.logger.error("Failed to switch to app before clicking %s", element_key)
            return {"error": "Failed to switch to app"}

        element = self.owner.element_finder.wait_for_element_clickable(element_key, timeout=timeout)
        if not element:
            self.logger.error("Failed to find clickable element: %s", element_key)
            return {"error": error_message}

        if not self.owner.gesture_handler.click_element_at(element, **(click_kwargs or {})):
            self.logger.error("Failed to click element: %s", element_key)
            return {"error": error_message}

        return {"success": True}

    # 麦克风开关不在这里：MicManager 拥有 content-desc 状态读取与麦位前置检查，
    # 盲点击的 ui_actions.toggle_mic 已删除（见 managers/mic_manager.py）。
