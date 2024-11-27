from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from ..utils.app_handler import AppHandler
import time
class QQMusicHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)

    def hide_player(self):
        self.driver.press_keycode(4)  # Android back key code
        print("Pressed back key to hide player panel")
        """Hide the music player by pressing back key if visible"""

    def navigate_to_home(self):
        """Navigate back to home page"""
        # Keep clicking back until no more back buttons found
        while True:
            try:
                back_button = self.driver.find_element(
                    AppiumBy.XPATH,
                    self.config['elements']['back_button']
                )
                back_button.click()
                print(f"Clicked back button")
            except:
                # No back button found, assume we're at home page
                print(f"No back button found, assume we're at home page")
                break

    def play_music(self, music_query):
        """Search and play music"""
        self.switch_to_app()
        print(f"Switched to QQ Music app")
        
        # Hide player if visible
        self.hide_player()
        print(f"Attempted to hide player")
        
        # Go back to home page
        self.navigate_to_home()
        print(f"Navigated to home page")
            
        # Find search entry
        search_entry = self.driver.find_element(
            AppiumBy.XPATH,
            self.config['elements']['search_entry']
        )
        search_entry.click()
        print(f"Clicked search entry")
                    
        # Input search query and press enter
        search_box = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['search_box']
            )
        search_box.send_keys(music_query)
        print(f"Input search query: {music_query}")
        
        self.press_enter(search_box)
        print(f"Pressed enter to search")
            
        # Click play button
        play_button = self.driver.find_element(
            AppiumBy.ID, 
            self.config['elements']['play_button']
        )
        play_button.click()
        print(f"Clicked play button")

