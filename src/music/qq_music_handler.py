from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from ..utils.app_handler import AppHandler
from ..utils.lyrics_formatter import LyricsFormatter
import time
import re

class QQMusicHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)
        self.lyrics_formatter = None  # Will be set by app_controller

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

    def toggle_accompaniment(self, enable):
        """Toggle accompaniment mode
        Args:
            enable: bool, True to enable, False to disable
        Returns:
            dict: {'enabled': 'on'/'off'}
        """
        try:
            self.switch_to_app()
            print("Switched to QQ Music app")

            # Try to find more button in play panel
            try:
                time.sleep(2)
                more_button = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['more_in_play_panel']
                )
            except:
                # If not found, try to activate play panel first
                print("More button not found, trying to activate play panel")
                self.press_back()
                print("Close unexpected screen")
                time.sleep(1)
                playing_bar = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['playing_bar']
                )
                playing_bar.click()
                print("Clicked playing bar")
                time.sleep(1)
                more_button = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['more_in_play_panel']
                )

            # Click more button
            more_button.click()
            print("Clicked more button")
            time.sleep(1)

            # Scroll menu to find accompaniment menu
            for _ in range(5):
                self.press_dpad_down()
            print("Scrolled menu")

            # Click accompaniment menu
            accompaniment_menu = self.driver.find_element(
                AppiumBy.XPATH,
                self.config['elements']['accompaniment_menu']
            )
            accompaniment_menu.click()
            print("Clicked accompaniment menu")
            time.sleep(1)

            # Find switch and check current state
            switch = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['accompaniment_switch']
            )
            current_state = switch.get_attribute('content-desc')
            is_on = current_state == "伴唱已开启"
            print(f"Current accompaniment state: {'on' if is_on else 'off'}")

            # Toggle if needed
            if (enable and not is_on) or (not enable and is_on):
                time.sleep(1)
                max_retries = 9
                retry_count = 0
                target_state = not is_on
                
                while retry_count < max_retries:
                    try:
                        # Get fresh switch element
                        switch = self.driver.find_element(
                            AppiumBy.ID,
                            self.config['elements']['accompaniment_switch']
                        )
                        switch.click()
                        print(f"Attempt {retry_count + 1}: Toggled accompaniment switch")
                        time.sleep(1)
                        
                        # Check new state
                        switch = self.driver.find_element(
                            AppiumBy.ID,
                            self.config['elements']['accompaniment_switch']
                        )
                        current_state = switch.get_attribute('content-desc')
                        is_on = current_state == "伴唱已开启"
                        
                        if is_on == target_state:
                            print(f"Successfully toggled accompaniment to {'on' if is_on else 'off'}")
                            break
                        else:
                            print(f"Attempt {retry_count + 1}: Toggle failed, current state: {'on' if is_on else 'off'}")
                            retry_count += 1
                            time.sleep(1)
                    except Exception as e:
                        print(f"Attempt {retry_count + 1}: Error during toggle: {str(e)}")
                        retry_count += 1
                        time.sleep(1)
                
                if retry_count >= max_retries:
                    print("Failed to toggle accompaniment after maximum retries")

            return {
                'enabled': 'on' if is_on else 'off'
            }

        except Exception as e:
            print(f"Error toggling accompaniment: {str(e)}")
            return {
                'enabled': 'unknown'
            }

    def increase_volume(self):
        """Increase the device volume"""
        try:
            self.press_volume_up()
        except Exception as e:
            print(f"Error increasing volume: {str(e)}")

    def decrease_volume(self):
        """Decrease the device volume"""
        try:
            self.press_volume_down()
        except Exception as e:
            print(f"Error decreasing volume: {str(e)}")

    def get_lyrics(self):
        """Get lyrics of current playing song"""
        try:
            self.switch_to_app()
            print("Switched to QQ Music app")

            # Try to find info dot button
            try:
                info_dot = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['info_dot']
                )
            except:
                # If not found, try to activate play panel first
                print("Info dot not found, trying to activate play panel")
                self.press_back()
                print("Close unexpected screen")
                time.sleep(1)
                playing_bar = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['playing_bar']
                )
                playing_bar.click()
                print("Clicked playing bar")
                time.sleep(1)
                info_dot = self.driver.find_element(
                    AppiumBy.ID,
                    self.config['elements']['info_dot']
                )

            # Click info dot
            info_dot.click()
            print("Clicked info dot")
            time.sleep(1)

            # Click details link
            details_link = self.driver.find_element(
                AppiumBy.ID,
                self.config['elements']['details_link']
            )
            details_link.click()
            print("Clicked details link")
            time.sleep(2)  # Wait for lyrics to load

            # Get lyrics
            lyrics_element = self.driver.find_element(
                AppiumBy.XPATH,
                self.config['elements']['song_lyrics']
            )
            raw_lyrics = lyrics_element.text
            
            # Extract language from lyrics text
            language = None
            language_match = re.search(r' 语种 (\w+)', raw_lyrics)
            if language_match:
                language = language_match.group(1)
            
            # Format lyrics
            formatted_lyrics = self.lyrics_formatter.format_lyrics(raw_lyrics, language)
            print("Formatted lyrics")

            # Go back to main screen
            self.press_back()
            time.sleep(0.5)
            self.press_back()
            print("Returned to main screen")

            return {
                'lyrics': formatted_lyrics if formatted_lyrics else "No lyrics available"
            }

        except Exception as e:
            print(f"Error getting lyrics: {str(e)}")
            return {
                'lyrics': "Failed to get lyrics"
            }

    def set_lyrics_formatter(self, formatter):
        self.lyrics_formatter = formatter

