from __future__ import annotations

import time

from ushareiplay.core.driver_decorator import with_driver_recovery


class KeyActions:
    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.owner, name)

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger

    @property
    def error_count(self):
        return self.owner.error_count

    @error_count.setter
    def error_count(self, value):
        self.owner.error_count = value

    @with_driver_recovery(retry=False, op="write")
    def switch_to_app(self):
        """Switch to specified app"""
        self.driver.activate_app(self.config["package_name"])
        time.sleep(0.1)
        return True

    @with_driver_recovery(retry=False, op="write")
    def close_app(self):
        """关闭应用"""
        self.driver.terminate_app(self.config["package_name"])

    @with_driver_recovery(retry=False, op="write")
    def switch_to_activity(self, activity):
        """Switch to the specified activity"""
        package_name = self.config["package_name"]
        command = f"am start -n {package_name}/{activity}"
        self.driver.execute_script("mobile: shell", {"command": command})

    @with_driver_recovery(retry=False, op="write")
    def press_enter(self, element):
        """
        Press Enter key on the given element
        Args:
            element: The WebElement to send Enter key to
        """
        self.driver.press_keycode(66)
        self.logger.debug("Pressed Return Key")

    @with_driver_recovery(retry=False, op="write")
    def press_back(self):
        """Press Android back button"""
        self.driver.press_keycode(4)  # Android back key code
        self.error_count = 0
        self.logger.debug("Pressed back button")
        return True

    @with_driver_recovery(retry=False, op="write")
    def press_dpad_down(self):
        """Press Android DPAD down button"""
        self.driver.press_keycode(20)  # KEYCODE_DPAD_DOWN
        self.logger.debug("Pressed DPAD down button")

    @with_driver_recovery(retry=False, op="write")
    def press_volume_up(self):
        """Press Android volume up button"""
        self.driver.press_keycode(24)  # KEYCODE_VOLUME_UP
        self.logger.debug("Pressed volume up button")

    @with_driver_recovery(retry=False, op="write")
    def press_volume_down(self):
        """Press Android volume down button"""
        self.driver.press_keycode(25)  # KEYCODE_VOLUME_DOWN
        self.logger.debug("Pressed volume down button")

    @with_driver_recovery(retry=False, op="write")
    def press_right_key(self, times=1):
        """Simulate pressing the right key multiple times
        Args:
            times: int, number of times to press the right key
        """
        for _ in range(times):
            self.driver.execute_script(
                "mobile: shell", {"command": "input keyevent KEYCODE_DPAD_RIGHT"}
            )
            time.sleep(0.1)  # Small delay between key presses

    @with_driver_recovery(retry=False, op="write")
    def set_clipboard_text(self, text):
        """Set clipboard text using Appium's native method
        Args:
            text: str, text to be copied to clipboard
        """
        self.driver.set_clipboard_text(text)
        self.logger.debug(f"Copied '{text}' to clipboard")

    @with_driver_recovery(retry=False, op="write")
    def paste_text(self):
        """Execute paste operation using Android keycode"""
        self.driver.press_keycode(279)  # KEYCODE_PASTE = 279
        self.logger.debug("Pressed paste key")
