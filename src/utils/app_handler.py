import time


class AppHandler:
    def __init__(self, driver, config):
        self.driver = driver
        self.config = config

    def switch_to_app(self):
        """切换到指定应用"""
        self.driver.activate_app(self.config['package_name'])
        time.sleep(1)

    def close_app(self):
        """关闭应用"""
        self.driver.terminate_app(self.config['package_name'])
    
    def switch_to_activity(self, activity):
        """Switch to the specified activity"""
        package_name = self.config['package_name']
        command = f'am start -n {package_name}/{activity}'
        self.driver.execute_script('mobile: shell', {'command': command})

    def press_enter(self, element):
        """
        Press Enter key on the given element
        Args:
            element: The WebElement to send Enter key to
        """
        self.driver.press_keycode(66)
        print('try 66')

    def press_back(self):
        """Press Android back button"""
        self.driver.press_keycode(4)  # Android back key code
        print("Pressed back button")

    def press_dpad_down(self):
        """Press Android DPAD down button"""
        self.driver.press_keycode(20)  # KEYCODE_DPAD_DOWN
        print("Pressed DPAD down button")

    def press_volume_up(self):
        """Press Android volume up button"""
        self.driver.press_keycode(24)  # KEYCODE_VOLUME_UP
        print("Pressed volume up button")

    def press_volume_down(self):
        """Press Android volume down button"""
        self.driver.press_keycode(25)  # KEYCODE_VOLUME_DOWN
        print("Pressed volume down button")
