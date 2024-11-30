from appium.webdriver.common.appiumby import AppiumBy
from appium.webdriver.common.touch_action import TouchAction
from ..utils.app_handler import AppHandler
from ..utils.lyrics_formatter import LyricsFormatter
import time
import re
import pytesseract
from PIL import Image
import io
import base64
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput


class QQMusicHandler(AppHandler):
    def __init__(self, driver, config):
        super().__init__(driver, config)
        self.lyrics_formatter = None  # Will be set by app_controller

        # Optimize driver settings
        self.driver.update_settings({
            "waitForIdleTimeout": 0,  # Don't wait for idle state
            "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
            "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
        })

    def hide_player(self):
        self.press_back()
        print("Hide player panel")
        time.sleep(1)

    def navigate_to_home(self):
        """Navigate back to home page"""
        # Keep clicking back until no more back buttons found
        while True:
            back_button = self.try_find_element(
                AppiumBy.XPATH,
                self.config['elements']['back_button']
            )

            if back_button:
                back_button.click()
                print(f"Clicked back button")
            else:
                search_entry = self.try_find_element(
                    AppiumBy.XPATH,
                    self.config['elements']['search_entry']
                )
                if search_entry:
                    print(f"Found search entry, assume we're at home page")
                    return
                else:
                    self.press_back()

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
        try:
            self.switch_to_app()
            print(f"Switched to QQ Music app")

            # Hide player if visible
            self.hide_player()
            print(f"Attempted to hide player")

            # Go back to home page
            self.navigate_to_home()
            print(f"Navigated to home page")

            # Find search entry
            search_entry = self.wait_for_element_clickable(
                AppiumBy.XPATH,
                self.config['elements']['search_entry']
            )
            search_entry.click()
            print(f"Clicked search entry")

            search_box = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['search_box']
            )
            print(f"Found search box")
            search_box.click()  # Ensure focus
            search_box.send_keys(music_query)  # KEYCODE_PASTE
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

            # Reset wait time back to default

            return playing_info

        except Exception as e:
            raise e

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
        self.switch_to_app()
        print("Switched to QQ Music app")

        switch = self.try_find_element(AppiumBy.ID, self.config['elements']['accompaniment_switch'])
        if not switch:
            print("Switch not found, trying to find more button")
            while True:
                more_button = self.try_find_element(AppiumBy.ID, self.config['elements']['more_in_play_panel'])
                if more_button:
                    break
                playing_bar = self.try_find_element(AppiumBy.ID, self.config['elements']['playing_bar'])
                if playing_bar:
                    playing_bar.click()
                    print("Clicked playing bar")
                    break
                else:
                    self.press_back()

            # Check if supporting accompaniment mode

            acc_tag = self.try_find_element(AppiumBy.ID, self.config['elements']['accompaniment_tag'])
            if acc_tag is None:
                return {
                    'enabled': 'Accompaniment not supported for current song, please try following songs'
                }

            more_button = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements']['more_in_play_panel'])
            more_button.click()
            print("Clicked more button")

            accompaniment_menu = None
            for _ in range(9):
                self.press_dpad_down()
                accompaniment_menu = self.try_find_element(AppiumBy.XPATH,
                                                           self.config['elements']['accompaniment_menu'])
                if accompaniment_menu:
                    break
            print("Scrolled menu")
            if not accompaniment_menu:
                print(f'error: cannot find accompaniment_menu in more menu')
                return None

            # Click accompaniment menu
            accompaniment_menu = self.wait_for_element_clickable(AppiumBy.XPATH,
                                                                 self.config['elements']['accompaniment_menu'])
            accompaniment_menu.click()
            print("Clicked accompaniment menu")
            switch = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements']['accompaniment_switch'])
            print(f'Found accompaniment switch')
        else:
            print(f'Accompaniment switch already found')

        # Find switch and check current state
        current_state = switch.get_attribute('content-desc')
        is_on = current_state == "伴唱已开启"
        print(f"Current accompaniment state: {'on' if is_on else 'off'}")

        # Toggle if needed
        if (enable and not is_on) or (not enable and is_on):
            while is_on != enable:
                switch.click()
                current_state = switch.get_attribute('content-desc')
                is_on = current_state == "伴唱已开启"
                if is_on != enable:
                    print(f"Failed to toggle accompaniment mode, current state: {current_state}")

        return {
            'enabled': 'on' if is_on else 'off'
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
            info_dot = self.try_find_element(AppiumBy.ID, self.config['elements']['info_dot'])
            if not info_dot:
                while True:
                    self.press_back()
                    info_dot = self.try_find_element(AppiumBy.ID, self.config['elements']['info_dot'])
                    if info_dot:
                        break
                    playing_bar = self.try_find_element(
                        AppiumBy.ID,
                        self.config['elements']['playing_bar']
                    )
                    if playing_bar:
                        playing_bar.click()
                        print("Clicked playing bar")
                        break
            else:
                print(f'Found info dot')

            info_dot = self.wait_for_element_clickable(AppiumBy.ID, self.config['elements']['info_dot'], timeout=20)
            print(f'info_dot is clickable')
            # Click info dot
            info_dot.click()
            print("Clicked info dot")

            # Click details link
            details_link = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['details_link']
            )
            details_link.click()
            print("Clicked details link")

            # Wait for song_lyrics to appear and scroll to bottom
            song_lyrics = self.wait_for_element(
                AppiumBy.XPATH,
                self.config['elements']['song_lyrics']
            )
            if song_lyrics:
                # Scroll song_lyrics to bottom
                self.scroll_element(song_lyrics)
                print("Scrolled song_lyrics to bottom")
                time.sleep(1)  # Wait for scroll animation and DOM update
                
                # Now try to get full lyrics
                full_lyrics = self.get_full_lyrics()
                
                return {
                    'lyrics': full_lyrics if full_lyrics else "No lyrics available"
                }
            else:
                return {
                    'lyrics': "Song lyrics not found"
                }

        except Exception as e:
            print(f"Error getting lyrics: {str(e)}")
            return {
                'lyrics': "Failed to get lyrics"
            }

    def set_lyrics_formatter(self, formatter):
        self.lyrics_formatter = formatter

    def get_element_screenshot(self, element):
        """Get screenshot of specific element and perform OCR
        Args:
            element: WebElement to capture
        Returns:
            str: Recognized text
        """
        try:
            # Get element screenshot
            screenshot = element.screenshot_as_base64
            image_data = base64.b64decode(screenshot)
            image = Image.open(io.BytesIO(image_data))

            # # Get image size
            # width, height = image.size
            #
            # # Define crop region (top 80 pixels)
            # crop_box = (0, 500, width, 800)  # (left, top, right, bottom)
            # cropped_image = image.crop(crop_box)

            # Perform OCR with Chinese support
            text = pytesseract.image_to_string(
                image,
                lang='chi_sim+eng',  # Use both Chinese and English
                config='--psm 6'  # Assume uniform text block
            )

            return text.strip()
        except Exception as e:
            print(f"Error performing OCR: {str(e)}")
            return ""

    def start_ktv_mode(self, max_switches=9, switch_interval=1):
        """Start KTV mode to sync lyrics"""
        try:
            self.switch_to_app()
            print("Switched to QQ Music app")

            # Try to find live lyrics element
            live_lyrics = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['live_lyrics']
            )

            if not live_lyrics:
                # Try to activate player panel
                playing_bar = self.try_find_element(
                    AppiumBy.ID,
                    self.config['elements']['playing_bar']
                )
                if playing_bar:
                    playing_bar.click()
                    print("Clicked playing bar")
                    time.sleep(1)
                    live_lyrics = self.try_find_element(
                        AppiumBy.ID,
                        self.config['elements']['live_lyrics']
                    )

            if not live_lyrics:
                yield "Live lyrics not available"
                return

            previous_lyrics = ""
            switches = 0

            while switches < max_switches:
                # Get lyrics using OCR
                current_lyrics = self.get_element_screenshot(live_lyrics)

                # Only yield if lyrics changed and not empty
                if current_lyrics and current_lyrics != previous_lyrics:
                    previous_lyrics = current_lyrics
                    yield current_lyrics

                time.sleep(switch_interval)
                switches += 1

                # Try to find live lyrics again
                live_lyrics = self.try_find_element(
                    AppiumBy.ID,
                    self.config['elements']['live_lyrics']
                )
                if not live_lyrics:
                    break

        except Exception as e:
            print(f"Error in KTV mode: {str(e)}")
            yield "Error getting live lyrics"

    def get_full_lyrics(self):
        """Get full lyrics by scrolling and combining all parts"""
        try:
            # First find lyrics container
            lyrics_container = self.wait_for_element(
                AppiumBy.XPATH,
                self.config['elements']['full_lyrics']
            )
            
            if not lyrics_container:
                return "No lyrics container found"
            
            # Print lyrics container info
            print(f"Lyrics container found: {lyrics_container}")
            print(f"Container size: {lyrics_container.size}")
            print(f"Container location: {lyrics_container.location}")
            print(f"Container tag name: {lyrics_container.tag_name}")
            print(f"Container text: {lyrics_container.text}")
            print(f"Container element id: {lyrics_container.id}")
            
            # Get initial lyrics elements
            lyrics_elements = lyrics_container.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            if not lyrics_elements:
                return "No lyrics elements found"
            
            # Collect initial lyrics
            lyrics_list = []
            seen_ids = set()
            last_element_id = None

            for element in lyrics_elements:
                text = element.text
                if text:
                    element_id = element.id
                    seen_ids.add(element_id)
                    lyrics_list.append(text)
                    last_element_id = element_id
            
            print(f"Collected {len(lyrics_list)} initial lyrics")
            print(f"Last element id: {last_element_id}")
            
            # Scroll to bottom to reveal more lyrics
            self.scroll_element(lyrics_container)
            print("Scrolled lyrics container to bottom")
            time.sleep(1)  # Wait for scroll animation
            
            # Get additional lyrics elements after scroll
            lyrics_elements = lyrics_container.find_elements(AppiumBy.CLASS_NAME, "android.widget.TextView")
            found_last_element = False

            count = 0
            for element in lyrics_elements:
                element_id = element.id
                # Skip until we find the last element from previous section
                if not found_last_element:
                    if element_id == last_element_id:
                        found_last_element = True
                    continue
                
                # Add new lyrics that we haven't seen before
                if element_id not in seen_ids:
                    text = element.text
                    if text:
                        count += len(text)
                        if count + len(text) > 500:
                            break
                        seen_ids.add(element_id)
                        lyrics_list.append(text)
            
            print(f"Collected total {len(lyrics_list)} lyrics after scroll")
            
            # Join all lyrics
            full_lyrics = '\n'.join(lyrics_list)
            print("Combined all lyrics")
            return full_lyrics
            
        except Exception as e:
            print(f"Error getting full lyrics: {str(e)}")
            return "Error getting full lyrics"

    def scroll_element(self, element, start_y_percent=0.75, end_y_percent=0.25):
        """Scroll element using W3C Actions API
        Args:
            element: WebElement to scroll
            start_y_percent: Start y position as percentage of element height (0.75 = 75% from top)
            end_y_percent: End y position as percentage of element height (0.25 = 25% from top)
        """
        try:
            # Get element location and size
            size = element.size
            location = element.location
            
            # Calculate scroll coordinates
            start_x = location['x'] + size['width'] // 2
            start_y = location['y'] + int(size['height'] * start_y_percent)
            end_y = location['y'] + int(size['height'] * end_y_percent)
            
            # Create pointer input
            actions = ActionChains(self.driver)
            pointer = PointerInput(interaction.POINTER_TOUCH, "touch")
            
            # Create action sequence
            actions.w3c_actions = ActionBuilder(self.driver, mouse=pointer)
            actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
            actions.w3c_actions.pointer_action.pointer_down()
            # actions.w3c_actions.pointer_action.pause(0.01)
            actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
            actions.w3c_actions.pointer_action.release()
            
            # Perform action
            actions.perform()
            print(f"Scrolled element from {start_y} to {end_y}")
            time.sleep(1)  # Wait for scroll animation
            
        except Exception as e:
            print(f"Error scrolling element: {str(e)}")
