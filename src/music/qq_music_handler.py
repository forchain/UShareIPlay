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
import traceback


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

            search_box = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['search_box']
            )
            if not search_box:
                print(f"Cannot find search entry")

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
            else:
                clear_search = self.wait_for_element_clickable(
                    AppiumBy.ID,
                    self.config['elements']['clear_search']
                )
                clear_search.click()
                print(f"Clear search")

            # Find and click search box
            search_box = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['search_box']
            )
            print(f"Found search box")

            # Use clipboard operations from parent class
            self.set_clipboard_text(music_query)
            self.paste_text()

            self.select_song_tab()

            playing_info = self.get_playing_info()
            if not playing_info:
                playing_info = {
                    'song': music_query,
                    'singer': 'unknown'
                }
            print(f"Found playing info: {playing_info}")

            return playing_info

        except Exception as e:
            raise e

    def select_song_tab(self):
        """Select the 'Songs' tab in search results"""
        song_tab = self.wait_for_element_clickable(
            AppiumBy.XPATH,
            self.config['elements']['song_tab']
        )
        song_tab.click()
        print("Selected songs tab")

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
        """Skip to next song"""
        try:
            # Get current info before skip
            current_info = self.get_playback_info()
            
            # Execute shell command to simulate media button press
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_NEXT'
                }
            )
            print("Sent media next key event")
            
            # Return song info
            return {
                'song': current_info.get('song', 'Unknown'),
                'singer': current_info.get('singer', 'Unknown')
            }
            
        except Exception as e:
            print(f"Error skipping song: {str(e)}")
            traceback.print_exc()
            return {
                'song': 'Unknown',
                'singer': 'Unknown'
            }

    def pause_song(self, pause_state=None):
        """
        Pause/resume playback
        Args:
            pause_state: None for toggle, 1 for pause, 0 for play
        Returns:
            dict: Current playing info or error
        """
        try:
            # Get current playback info
            current_info = self.get_playback_info()
            if 'error' in current_info:
                return current_info
                
            # Get current state
            is_playing = current_info['state'] == "Playing"
            
            # Determine if we need to change state
            should_pause = False
            if pause_state is None:
                # Toggle mode
                should_pause = is_playing
            else:
                # Explicit mode
                should_pause = pause_state == 1
                if (should_pause and not is_playing) or (not should_pause and is_playing):
                    # State already matches desired state
                    return {
                        'song': current_info['song'],
                        'singer': current_info['singer'],
                        'action': 'Paused' if not is_playing else 'Resumed'
                    }
            
            # Execute media control command
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_PLAY_PAUSE'
                }
            )
            print("Sent media play/pause key event")
            
            return {
                'song': current_info['song'],
                'singer': current_info['singer'],
                'action': 'Paused' if should_pause else 'Resumed'
            }
            
        except Exception as e:
            print(f"Error controlling playback: {str(e)}")
            traceback.print_exc()
            return {'error': str(e)}

    def get_volume_level(self):
        """Get current volume level"""
        try:
            # Execute shell command to get volume
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys audio'
                }
            )

            # Parse volume level
            if result:
                # Split by "- STREAM_MUSIC:" first
                parts = result.split('- STREAM_MUSIC:')
                if len(parts) > 1:
                    # Find first streamVolume in second part
                    match = re.search(r'streamVolume:(\d+)', parts[1])
                    if match:
                        volume = int(match.group(1))
                        print(f"Current volume: {volume}")
                        return volume
            return 0
        except Exception as e:
            print(f"Error getting volume level: {str(e)}")
            traceback.print_exc()
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

    def adjust_volume(self, delta=None):
        """
        Adjust volume level
        Args:
            delta: int, positive to increase, negative to decrease, None to just get current level
        Returns:
            dict: Result with level and times if adjusted, or error
        """
        try:
            if delta is None:
                # Just get current volume
                return {'level': self.get_volume_level()}
            
            # Adjust volume
            times = abs(delta)
            for i in range(times):
                if delta > 0:
                    self.press_volume_up()
                    print(f"Increased volume ({i + 1}/{times})")
                else:
                    self.press_volume_down()
                    print(f"Decreased volume ({i + 1}/{times})")
            
            # Get final volume level
            level = self.get_volume_level()
            return {
                'level': level,
                'times': times
            }
            
        except Exception as e:
            print(f"Error adjusting volume: {str(e)}")
            return {'error': str(e)}

    def get_lyrics(self):
        """Get lyrics of current playing song"""
        try:
            self.switch_to_app()
            print("Switched to QQ Music app")

            # Press back to exit most interfaces
            self.press_back()
            search_entry = self.try_find_element(
                AppiumBy.XPATH,
                self.config['elements']['search_entry']
            )
            if not search_entry:
                self.press_back()
            print("Pressed back to clean up interface")

            time.sleep(0.5)  # Wait for animation
            # Try to find and click playing bar if exists
            playing_bar = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['playing_bar']
            )
            if playing_bar:
                playing_bar.click()
                print("Found and clicked playing bar")
                time.sleep(0.5)  # Wait for animation

            # Find more menu in play panel
            more_menu = self.wait_for_element(
                AppiumBy.ID,
                self.config['elements']['more_in_play_panel']
            )
            if not more_menu:
                return {'error': 'Cannot find playing interface, please try again'}

            # Get screen dimensions for swipe
            screen_size = self.driver.get_window_size()
            start_x = int(screen_size['width'] * 0.8)  # Start from 80% of width
            end_x = int(screen_size['width'] * 0.1)  # End at 20% of width
            y = int(screen_size['height'] * 0.5)  # Middle of screen

            # Swipe to lyrics page
            self.driver.swipe(start_x, y, end_x, y, 500)  # 1000ms = 1s
            print("Swiped to lyrics page")

            # Find and click lyrics tool button
            lyrics_tool = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['lyrics_tool']
            )
            if not lyrics_tool:
                return {'error': 'Cannot find lyrics tool'}

            # Check if lyrics are available
            no_lyrics = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['no_lyrics']
            )
            if no_lyrics:
                return {'error': 'No lyrics available for this song'}

            lyrics_tool.click()
            print("Clicked lyrics tool")

            # Find and click lyrics poster button
            lyrics_poster = self.wait_for_element(
                AppiumBy.XPATH,
                self.config['elements']['lyrics_poster']
            )
            if not lyrics_poster:
                return {'error': 'Cannot find lyrics poster option'}
            if not lyrics_poster.is_enabled():
                return {'error': 'Lyrics poster disabled'}

            lyrics_poster.click()
            print("Clicked lyrics poster")
            self.wait_for_element(
                AppiumBy.ID,
                self.config['elements']['lyrics_line']
            )

            # Quick swipe to top of lyrics
            self.driver.swipe(
                screen_size['width'] // 2,  # Start from middle x
                screen_size['height'] * 0.3,  # Start from bottom part
                screen_size['width'] // 2,  # End at same x
                screen_size['height'] * 0.9,  # End at top
                100  # Fast swipe (300ms)
            )
            print("Quick swipe to top of lyrics")
            time.sleep(0.5)  # Wait for scroll to settle

            # Collect lyrics
            all_lyrics = []  # Use list to maintain order
            total_chars = 0
            screen_height = screen_size['height']
            previous_lines = []  # Store previous batch of lyrics

            while True:
                try:
                    # Find all lyrics lines
                    lyrics_lines = self.wait_for_element(
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )
                    if not lyrics_lines:
                        print(f'No lyrics lines found')
                        break

                    # Get fresh elements each time
                    lyrics_lines = self.driver.find_elements(
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )

                    # Get current batch of lyrics, handle StaleElementReferenceException
                    current_lines = []
                    for line in lyrics_lines:
                        try:
                            text = line.text.strip()
                            if text:
                                current_lines.append(text)
                        except:
                            continue

                    if not current_lines:
                        print("No valid lyrics in current view")
                        break

                    # Process new lyrics, handling overlapping
                    if previous_lines:
                        # Find overlap between previous end and current start
                        overlap_size = 0
                        for i in range(min(len(previous_lines), len(current_lines))):
                            if previous_lines[-i - 1:] == current_lines[:i + 1]:
                                overlap_size = i + 1

                        # Add only non-overlapping lines
                        new_lines = current_lines[overlap_size:]
                    else:
                        new_lines = current_lines

                    # Add new lines while checking character limit
                    too_long = False
                    for line in new_lines:
                        if total_chars + len(line) > 400:
                            print("Would exceed character limit, stopping")
                            too_long = True
                            break
                        all_lyrics.append(line)
                        total_chars += len(line)
                    if too_long:
                        break

                    # Check for end marker
                    end_marker = self.try_find_element(
                        AppiumBy.XPATH,
                        self.config['elements']['lyrics_end'],
                        log=False
                    )
                    if end_marker:
                        print("Reached lyrics end")
                        break

                    # Store current lines for next iteration
                    previous_lines = current_lines

                    # Scroll up half screen
                    self.driver.swipe(
                        screen_size['width'] // 2,
                        screen_height * 0.7,
                        screen_size['width'] // 2,
                        screen_height * 0.3,
                        400
                    )

                except Exception as e:
                    print(f"Error in lyrics collection loop: {str(e)}")
                    break

            # Join lyrics with newlines
            final_lyrics = '\n'.join(all_lyrics)
            print(f"Collected {len(all_lyrics)} lines of lyrics")

            # Press back to return
            self.press_back()

            return {'lyrics': final_lyrics if final_lyrics else "No lyrics available"}

        except Exception as e:
            print(f"Error getting lyrics: {str(e)}")
            traceback.print_exc()
            return {'error': str(e)}

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

    def get_playback_info(self):
        """Get current playback information including song info and state"""
        try:
            # Get media session info
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys media_session'
                }
            )
            
            # Parse metadata
            metadata = {}
            state = "Unknown"
            
            if result:
                # Get metadata
                meta_match = re.search(r'metadata: size=\d+, description=(.*?)(?=\n)', result)
                if meta_match:
                    meta_parts = meta_match.group(1).split(', ')
                    if len(meta_parts) >= 3:
                        metadata = {
                            'song': meta_parts[0],
                            'singer': meta_parts[1],
                            'album': meta_parts[2]
                        }
                
                # Get playback state
                state_match = re.search(r'state=PlaybackState {state=(\d+)', result)
                if state_match:
                    state_code = int(state_match.group(1))
                    state = {
                        0: "None",
                        1: "Stopped",
                        2: "Paused",
                        3: "Playing",
                        4: "Fast Forwarding",
                        5: "Rewinding",
                        6: "Buffering",
                        7: "Error",
                        8: "Connecting",
                        9: "Skipping to Next",
                        10: "Skipping to Previous",
                        11: "Skipping to Queue Item"
                    }.get(state_code, "Unknown")
            
            return {
                'song': metadata.get('song', 'Unknown'),
                'singer': metadata.get('singer', 'Unknown'),
                'album': metadata.get('album', 'Unknown'),
                'state': state
            }
            
        except Exception as e:
            print(f"Error getting playback info: {str(e)}")
            traceback.print_exc()
            return {'error': str(e)}
