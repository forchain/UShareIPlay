class AppHandler:
    def __init__(self, driver, config):
        self.driver = driver
        self.config = config

    def switch_to_app(self):
        """切换到指定应用"""
        self.driver.activate_app(self.config['package_name'])

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
