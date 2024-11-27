from appium.webdriver.common.appiumby import AppiumBy
from ..utils.app_handler import AppHandler

class QQMusicHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)

    def play_music(self, song, singer):
        """搜索并播放音乐"""
        try:
            # 打开搜索框
            search_box = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['search_box'].replace('id=', '')
            )
            search_box.send_keys(f"{song} {singer}")
            
            # 点击搜索
            search_button = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['search_button'].replace('id=', '')
            )
            search_button.click()
            
            # 选择第一首歌
            first_song = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['first_song'].replace('id=', '')
            )
            first_song.click()
            
            # 点击播放
            play_button = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['play_button'].replace('id=', '')
            )
            play_button.click()
        except Exception as e:
            print(f"Error playing music: {str(e)}") 