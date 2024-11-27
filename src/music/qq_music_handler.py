from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from ..utils.app_handler import AppHandler
import time

class QQMusicHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)

    def hide_player(self):
        self.press_back()
        print("Hide player panel")
        time.sleep(1)

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

    def get_playing_info(self):
        """Get current playing song and singer info"""
        try:
            song_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['song_name']
            )
            singer_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['singer_name']
            )
            return {
                'song': song_element.text,
                'singer': singer_element.text
            }
        except Exception as e:
            print(f"Error getting playing info: {str(e)}")
            return None
    def get_current_playing(self):
        """Get current playing song and singer info"""
        try:
            song_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['current_song']
            )
            singer_element = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['current_singer']
            )
            return {
                'song': song_element.text,
                'singer': singer_element.text
            }
        except Exception as e:
            print(f"Error getting current playing info: {str(e)}")
            return None

    def _prepare_music_playback(self, music_query):
        """Common logic for preparing music playback"""
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
            
        playing_info = self.get_playing_info()
        if not playing_info:
            playing_info = {
                'song': music_query,
                'singer': 'unknown'
            }
        print(f"Found playing info: {playing_info}")
        
        return playing_info

    def play_music(self, music_query):
        """Search and play music"""
        try:
            playing_info = self._prepare_music_playback(music_query)
            # Click play button
            play_button = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['play_button']
            )
            play_button.click()
            print(f"Clicked play button")

            return playing_info

        except Exception as e:
            print(f"Error playing music: {str(e)}")
            return {
                'song': music_query,
                'singer': 'unknown'
            }

    def play_next(self, music_query):
        """Search and play next music"""
        try:
            playing_info = self._prepare_music_playback(music_query)
            # Click next button
            next_button = self.driver.find_element(
                AppiumBy.ID, 
                self.config['elements']['next_button']
            )
            next_button.click()
            print(f"Clicked next button")

            return playing_info

        except Exception as e:
            print(f"Error playing next music: {str(e)}")
            return {
                'song': music_query,
                'singer': 'unknown'
            }

    def skip_song(self):
        """Skip to next song using notification panel"""
        try:
            # Open notification panel
            self.driver.open_notifications()
            print("Opened notification panel")
            time.sleep(1)  # Wait for animation

            # Find and click skip button in notification
            skip_button = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['skip_button']
            )
            skip_button.click()
            print("Clicked skip button")
            time.sleep(1)  # Wait for song change

            # Get playing info
            playing_info = self.get_current_playing()
            if not playing_info:
                playing_info = {
                    'song': 'unknown',
                    'singer': 'unknown'
                }
            print(f"Now playing: {playing_info}")

            # Close notification panel
            self.press_back()
            print("Closed notification panel")

            return playing_info

        except Exception as e:
            print(f"Error skipping song: {str(e)}")
            return {
                'song': 'unknown',
                'singer': 'unknown'
            }

    def pause_song(self):
        """Pause current playing song using notification panel"""
        try:
            # Get current playing info before pause
            self.driver.open_notifications()
            print("Opened notification panel")
            time.sleep(1)  # Wait for animation

            # Get current playing info
            playing_info = self.get_current_playing()
            if not playing_info:
                playing_info = {
                    'song': 'unknown',
                    'singer': 'unknown'
                }
            print(f"Current playing: {playing_info}")

            # Find and click pause button
            pause_button = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['pause_button']
            )
            pause_button.click()
            print("Clicked pause button")
            time.sleep(1)  # Wait for pause action

            # Close notification panel
            self.press_back()
            print("Closed notification panel")

            return playing_info

        except Exception as e:
            print(f"Error pausing song: {str(e)}")
            return {
                'song': 'unknown',
                'singer': 'unknown'
            }

    def get_volume_level(self):
        """Get current volume level"""
        try:
            # Execute shell command to get volume
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys audio | grep "STREAM_MUSIC" | grep -o "[0-9]*/[0-9]*"'
                }
            )
            
            # Parse volume level
            if result:
                current, max_vol = map(int, result.strip().split('/'))
                volume_percentage = int((current / max_vol) * 100)
                print(f"Current volume: {volume_percentage}%")
                return volume_percentage
            return 0
        except Exception as e:
            print(f"Error getting volume level: {str(e)}")
            return 0

    def increase_volume(self):
        """Increase the device volume"""
        try:
            self.driver.press_keycode(24)  # KEYCODE_VOLUME_UP
            print("Increased volume")
        except Exception as e:
            print(f"Error increasing volume: {str(e)}")

    def decrease_volume(self):
        """Decrease the device volume"""
        try:
            self.driver.press_keycode(25)  # KEYCODE_VOLUME_DOWN
            print("Decreased volume")
        except Exception as e:
            print(f"Error decreasing volume: {str(e)}")

