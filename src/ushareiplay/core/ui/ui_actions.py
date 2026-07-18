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

    def toggle_mic(self, enable: bool) -> dict:
        """Toggle the microphone while retaining MicManager's result contract."""
        try:
            if not self.owner.key_actions.switch_to_app():
                return {"error": "Failed to switch to app"}

            mic_button = self.owner.element_finder.try_find_element("toggle_mic")
            if not mic_button:
                return {"error": "Microphone button not found"}

            if not self.owner.gesture_handler.click_element_at(mic_button):
                return {"error": "Failed to click microphone button"}

            state = "开启" if enable else "关闭"
            self.logger.info("Clicked microphone button to %s", state)
            return {"state": state}
        except Exception as error:
            self.logger.error("Error toggling microphone: %s", error)
            return {"error": str(error)}
