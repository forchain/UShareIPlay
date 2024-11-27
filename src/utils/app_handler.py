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