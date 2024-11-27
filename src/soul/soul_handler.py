from appium.webdriver.common.appiumby import AppiumBy
from ..utils.app_handler import AppHandler

class SoulHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)

    def get_latest_message(self):
        """获取最新消息"""
        try:
            messages = self.driver.find_elements(
                AppiumBy.ID, 
                self.config['elements']['message_list'].replace('id=', '')
            )
            if messages:
                return messages[-1].text
            return None
        except Exception as e:
            print(f"Error getting message: {str(e)}")
            return None

    def send_message(self, message):
        """发送消息"""
        try:
            input_box = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['input_box'].replace('id=', '')
            )
            input_box.send_keys(message)
            
            send_button = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['send_button'].replace('id=', '')
            )
            send_button.click()
        except Exception as e:
            print(f"Error sending message: {str(e)}") 