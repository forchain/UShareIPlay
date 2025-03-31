from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import StaleElementReferenceException

from ..utils.app_handler import AppHandler
import time
import re
import traceback
import langdetect

# 在导入后设置种子
langdetect.DetectorFactory.seed = 0  # 使用赋值而不是调用


class QQMusicHandler(AppHandler):
    def __init__(self, driver, config, controller):
        super().__init__(driver, config, controller)

        self.ktv_mode = False  # KTV mode state
        self.last_lyrics = ""  # Store last recognized lyrics
        self.last_lyrics_lines = []
        self.no_skip = 0
        self.list_mode = 'unknown'

        # Optimize driver settings
        self.driver.update_settings({
            "waitForIdleTimeout": 0,  # Don't wait for idle state
            "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
            "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
        })

    def hide_player(self):
        self.press_back()
        self.logger.info("Hide player panel")
        time.sleep(1)

    def navigate_to_home(self):
        """Navigate back to home page"""
        # Keep clicking back until no more back buttons found
        n = 0
        while n < 9:
            search_entry = self.try_find_element_plus('search_entry')
            if search_entry:
                go_back = self.try_find_element_plus('go_back')
                if go_back:
                    go_back.click()
                    self.logger.info(f"Clicked go back button")
                else:
                    self.logger.info(f"Found search entry, assume we're at home page")
                    return True
            else:
                self.press_back()
                n += 1
        return False

    def get_playing_info(self):
        """Get current playing song and singer info"""
        song_element = self.try_find_element_plus("song_name")
        if not song_element:
            return {
                "song": "Unknown",
                "singer": "Unknown",
                "album": "Unknown",
            }
        song = song_element.text
        singer_element = self.try_find_element_plus("singer_name")
        if not song_element:
            return {
                "song": song,
                "singer": "Unknown",
                "album": "Unknown",
            }
        singer_album = singer_element.text.split('·')
        singer = singer_album[0]
        album = singer_album[1] if len(singer_album) > 1 else "Unknown"

        return {
            'song': song,
            'singer': singer,
            'album': album
        }

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

    def query_music(self, music_query: str):
        """Common logic for preparing music playback"""
        if not self.switch_to_app():
            self.logger.info(f"Failed to switched to QQ Music app")
            return False
        self.logger.info(f"Switched to QQ Music app")

        # Check if we're already in search mode

        play_all = self.try_find_element_plus('play_all')
        play_all_mini = self.try_find_element_plus('play_all_mini')
        play_singer = self.try_find_element_plus('play_singer')
        play_album = self.try_find_element_plus('play_album')
        if play_all or play_all_mini or play_singer or play_album:
            self.logger.info(f"Found play button, go back")
            self.press_back()

        singer_screen = self.try_find_element_plus('singer_screen', log=False)
        if singer_screen:
            self.logger.info(f"Hide singer screen 1")
            self.press_back()
        
        playlist_screen = self.try_find_element_plus('playlist_screen', log=False)
        if playlist_screen:
            self.logger.info(f"Hide playlist screen 1")
            self.press_back()

        search_box = self.try_find_element_plus('search_box', log=False)
        if not search_box:
            go_back = self.try_find_element_plus('go_back', log=False)
            if go_back:
                self.logger.info(f"Clicked Go Back button")
                go_back.click()
            else:
                self.press_back()
        else:
            singer_screen = self.try_find_element_plus('singer_screen', log=False)
            if singer_screen:
                self.logger.info(f"Hide singer screen 2")
                self.press_back()
            playlist_screen = self.try_find_element_plus('playlist_screen', log=False)
            if playlist_screen:
                self.logger.info(f"Hide playlist screen 2")
                self.press_back()

        go_home = False
        playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        search_box = None
        if playlist_entry:
            singer_screen = self.try_find_element_plus('singer_screen', log=False)
            if singer_screen:
                self.logger.info(f"Hide singer screen 3")
                self.press_back()
            playlist_screen = self.try_find_element_plus('playlist_screen', log=False)
            if playlist_screen:
                self.logger.info(f"Hide playlist screen 3")
                self.press_back()
            search_box = self.try_find_element_plus('search_box', log=False)
            if not search_box:
                go_home = True
        else:
            go_home = True

        if go_home:
            # Go back to home page
            self.navigate_to_home()
            self.logger.info(f"Navigated to home page")

            # Find search entry
            search_entry = self.wait_for_element_clickable_plus('search_entry')
            if search_entry:
                search_entry.click()
                self.logger.info(f"Clicked search entry")
            else:
                self.logger.error(f"failed to find search entry")
                return False

            # Find and click search box
            search_box = self.wait_for_element_clickable_plus('search_box')

        if search_box:
            clear_search = self.try_find_element_plus('clear_search', log=False)
            if clear_search:
                clear_search.click()
                self.logger.info(f"Clear search")
            try:
                search_box.click()
            except StaleElementReferenceException as e:
                self.logger.warning("Failed to click search box")
                search_box = self.wait_for_element_clickable_plus('search_box')
                if search_box:
                    search_box.click()
                    self.logger.info(f"Clicked search box")
                else:
                    self.logger.error(f"failed to find search box")
                    return False
        else:
            self.logger.error(f"Cannot find search entry")
            return False

        # Use clipboard operations from parent class
        self.set_clipboard_text(music_query)
        self.paste_text()
        return True

    def _prepare_music_playback(self, music_query):
        if not self.query_music(music_query):
            self.logger.error(f"Failed to query music query: {music_query}")
            playing_info = {
                'error': f"Failed to query music: {music_query}"
            }
            return playing_info

        self.select_song_tab()

        playing_info = self.get_playing_info()
        if not playing_info:
            self.logger.warning(f"No playing info found for query: {music_query}")
            playing_info = {
                'error': f"No playing info found for query: {music_query}"
            }
            return playing_info

        self.logger.info(f"Found playing info: {playing_info}")

        if self.list_mode == 'singer':
            if playing_info['song'].endswith('(Live)') or (
                    playing_info['singer'] and playing_info['singer'] == playing_info['album']):
                self.no_skip += 1

        studio_version = self.try_find_element_plus('studio_version', log=False)
        if studio_version:
            studio_version.click()
            self.logger.info("Alter to studio version")

        return playing_info

    def select_song_tab(self):
        """Select the 'Songs' tab in search results"""
        try:
            # Try to find song tab first
            song_tab = self.try_find_element_plus('song_tab')
            if not song_tab:
                # If not found, scroll music_tabs to left
                music_tabs = self.try_find_element_plus('music_tabs')
                if not music_tabs:
                    self.logger.error("Failed to find music tabs")
                    return False
                
                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location
                
                # Scroll to left
                self.driver.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )
                
                # Try to find song tab again
                song_tab = self.try_find_element_plus('song_tab')
                if not song_tab:
                    self.logger.error("Failed to find song tab after scrolling")
                    return False
            
            song_tab.click()
            self.logger.info("Selected songs tab")
            return True
            
        except Exception as e:
            self.logger.error(f"Error selecting song tab: {traceback.format_exc()}")
            return False

    def play_playlist(self, query: str):

        if not self.query_music(query):
            return {
                'error': 'Failed to query music playlist',
            }

        if not self.select_playlist_tab():
            return {
                'error': 'Failed to find playlist tab',
            }
        result = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['playlist_result']
        )
        result.click()

        play_button = self.wait_for_element_clickable(
            AppiumBy.ID, self.config['elements']['play_playlist']
        )
        if play_button:
            play_button.click()
        else:
            play_button = self.wait_for_element_clickable(
                AppiumBy.ID, self.config['elements']['playlist_item']
            )
            if play_button:
                play_button.click()
            else:
                return {'error': 'Failed to find play button'}

        return {
            'playlist': result.text,
        }

    def play_music(self, music_query):
        """Search and play music"""
        if music_query == '':
            playing_info = self.play_favorites()
            return playing_info

        playing_info = self._prepare_music_playback(music_query)
        if 'error' in playing_info:
            self.logger.error(f'Failed to play music {music_query}')
            return playing_info

        song_element = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['song_name']
        )
        song_element.click()
        self.logger.info(f"Select first song")

        return playing_info

    def play_next(self, music_query):
        """Search and play next music"""
        try:
            playing_info = self._prepare_music_playback(music_query)
            if 'error' in playing_info:
                self.logger.error(f'Failed to add music {music_query} to playlist')
                return playing_info

            # Click next button
            next_button = self.wait_for_element_clickable(
                AppiumBy.ID,
                self.config['elements']['next_button']
            )
            next_button.click()
            self.logger.info(f"Clicked next button")

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
            self.logger.info(f"Skipped {current_info['song']} by {current_info['singer']}")

            # Return song info
            return {
                'song': current_info.get('song', 'Unknown'),
                'singer': current_info.get('singer', 'Unknown')
            }

        except Exception as e:
            self.logger.error(f"Error skipping song: {traceback.format_exc()}")
            return {
                'song': 'Unknown',
                'singer': 'Unknown'
            }

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

    def adjust_volume(self, delta=None):
        """
        Adjust volume level
        Args:
            delta: int, positive to increase, negative to decrease, None to just get current level
        Returns:
            dict: Result with level and times if adjusted, or error
        """
        try:
            vol = self.get_volume_level()
            if delta is None:
                # Just get current volume
                return {'volume': vol}

            # Adjust volume
            if delta < 0:
                times = abs(delta) if vol + delta > 0 else vol
                for i in range(times):
                    self.press_volume_down()
                    self.logger.info(f"Decreased volume ({i + 1}/{times})")
            else:
                if vol > delta:
                    times = vol - delta
                    for i in range(times):
                        self.press_volume_down()
                        self.logger.info(f"Decreased volume ({i + 1}/{times})")
                else:
                    times = delta - vol
                    for i in range(times):
                        self.press_volume_up()
                        self.logger.info(f"Increased volume ({i + 1}/{times})")

            # Get final volume level
            vol = self.get_volume_level()
            self.logger.info(f"Adjusted volume to {vol}")
            return {
                'volume': vol,
            }
        except Exception as e:
            print(f"Error adjusting volume: {traceback.format_exc()}")
            return {'error': f'Failed to adjust volume to {delta}'}

    def get_playback_info(self):
        """Get current playback information including song info and state"""
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

        if not result:
            self.logger.error("Failed to get playback information")
            return None

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

    def toggle_ktv_mode(self, enable):
        """Toggle KTV mode
        Args:
            enable: bool, True to enable, False to disable
        """
        self.ktv_mode = enable
        print(f"KTV mode {'enabled' if enable else 'disabled'}")

        # Check if we need to switch to lyrics page when enabling KTV mode
        if enable:
            if not self.switch_to_app():
                return False
            # Try to find lyrics tool
            lyrics_tool = self.try_find_element(
                AppiumBy.ID,
                self.config['elements']['lyrics_tool']
            )

            if not lyrics_tool:
                # If not found, switch to lyrics page
                print("Not in lyrics page, switching to lyrics page...")
                result = self.switch_to_lyrics_page()
                if result and 'error' in result:
                    print(f"Error switching to lyrics page: {result['error']}")
                    return {'enabled': 'off'}  # Indicate that KTV mode could not be enabled

        return {'enabled': 'on' if enable else 'off'}

    def check_ktv_lyrics(self):
        if not self.switch_to_app():
            self.logger.error("Failed to switch to app")
            return {
                'error': "Failed to switch to app"
            }

        """Check current lyrics in KTV mode"""
        if not self.ktv_mode:
            return None  # 如果KTV模式未开启，则不执行

        close_poster = self.try_find_element_plus('close_poster', log=False)
        if close_poster:
            self.logger.info("Closing poster...")
            close_poster.click()

        lyrics_tool = self.wait_for_element_clickable_plus('lyrics_tool')
        if not lyrics_tool:
            self.ktv_mode = False
            self.logger.error("Failed to find lyrics tool")
            return {'error': 'Cannot find lyrics tool'}

        lyrics_tool.click()
        self.logger.info("Clicked lyrics tool")

        # 尝试查找并点击歌词海报
        lyrics_poster = self.wait_for_element_clickable_plus('lyrics_poster')
        if not lyrics_poster:
            # self.ktv_mode = False
            info = self.skip_song()
            self.logger.warning(f"Failed to find lyrics poster for {info['song']} by {info['singer']}")
            return {'error': f'Skip {info['song']} by {info['singer']} due to no lyrics poster option'}

        try:
            lyrics_poster.click()
        except StaleElementReferenceException as e:
            self.ktv_mode = False
            return {'error': 'Cannot click lyrics poster option'}
        self.logger.info("Clicked lyrics poster")

        # 找到所有的lyrics_box
        close_poster = self.wait_for_element_clickable_plus('close_poster')
        if not close_poster:
            self.ktv_mode = False
            self.logger.warning("No close poster")
            return {'error': 'No close poster'}

        current_lyrics = self.wait_for_element_clickable_plus('current_lyrics')
        finished = False
        if current_lyrics:
            try:
                y_coordinate = current_lyrics.location['y']
            except StaleElementReferenceException as e:
                self.logger.error(f"Error finding y coordinate")
                self.ktv_mode = False
                return {'error': 'Cannot get current lyrics coordinate'}

            if y_coordinate < 1000:
                finished = True
                self.logger.info("Found first line, song might be finished")
        if not finished:
            screen_size = self.driver.get_window_size()
            screen_height = screen_size['height']
            # Scroll up half screen
            self.driver.swipe(
                screen_size['width'] // 2,
                screen_height * 0.60,
                screen_size['width'] // 2,
                screen_height * 0.35,
                400
            )

        lyrics_boxes = self.driver.find_elements(
            AppiumBy.ID,
            self.config['elements']['lyrics_box']
        )

        if len(lyrics_boxes) <= 1:
            self.ktv_mode = False
            return {'error': 'Cannot find lyrics box'}

        # last element is a mistake
        lyrics_boxes.pop()

        found = False
        text = ""
        n = 0
        if not finished:
            for lyrics_box in lyrics_boxes:
                # 检查是否包含current_lyrics

                if found:
                    current_line = self.find_child_element(
                        lyrics_box,
                        AppiumBy.ID,
                        self.config['elements']['lyrics_line']
                    )
                    if current_line:
                        text += current_line.text + '\n'
                        n += 1
                else:
                    current_lyrics = self.find_child_element(
                        lyrics_box,
                        AppiumBy.ID,
                        self.config['elements']['current_lyrics']
                    )
                    if current_lyrics:
                        found = True

        if not found or finished:
            for lyrics_box in lyrics_boxes:
                current_line = self.find_child_element(
                    lyrics_box,
                    AppiumBy.ID,
                    self.config['elements']['lyrics_line']
                )
                if current_line:
                    text += current_line.text + '\n'

        if text:
            if text == self.last_lyrics:
                return {
                    'lyrics': 'Playing interlude..'
                }
            else:
                self.last_lyrics = text
                close_poster.click()
                # return all_lines
                return {
                    'lyrics': text
                }

        self.logger.error(f"lyrics is unavailable")
        self.ktv_mode = False
        return {
            'error': 'lyrics is unavailable'
        }

    def switch_to_playing_page(self):
        # Press back to exit most interfaces
        self.press_back()
        search_entry = self.try_find_element(
            AppiumBy.ID,
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
            try:
                playing_bar.click()
            except StaleElementReferenceException as e:
                self.logger.error(f"Failed to click playing bar")
                self.press_back()
                return {'error': 'Failed to switch to lyrics page, unexpected dialog might pop up'}

            self.logger.info("Found and clicked playing bar")
            time.sleep(0.5)  # Wait for animation

        # Find more menu in play panel
        more_menu = self.wait_for_element(
            AppiumBy.ID,
            self.config['elements']['more_in_play_panel']
        )
        if not more_menu:
            self.logger.error(f"playing interface is covered by unexpected dialog")
            return {'error': 'Cannot find playing interface, please try again'}

    def switch_to_lyrics_page(self):
        """
        Switch to lyrics page
        Returns:
            dict: None if successful, error dict if failed
        """
        error = self.switch_to_playing_page()
        if error:
            return error

        # Get screen dimensions for swipe
        screen_size = self.driver.get_window_size()
        start_x = int(screen_size['width'] * 0.8)  # Start from 80% of width
        end_x = int(screen_size['width'] * 0.1)  # End at 20% of width
        y = int(screen_size['height'] * 0.5)  # Middle of screen

        # Swipe to lyrics page
        self.driver.swipe(start_x, y, end_x, y, 500)  # 500ms = 0.5s
        print("Swiped to lyrics page")

        lyrics_tool = self.wait_for_element_clickable(
            AppiumBy.ID,
            self.config['elements']['lyrics_tool'])
        if not lyrics_tool:
            return {'error': 'Cannot find lyrics tool, please try again'}
        return None


    def get_playlist_info(self):
        """Get current playlist information
        Returns:
            str: Formatted playlist info or error dict
        """
        if not self.switch_to_app():
            self.logger.error("Cannot switch to QQ music")
            return {'error': 'Failed to switch to QQ Music app'}

        # Try to find playlist entry in playing panel first
        playlist_entry = self.try_find_element_plus('playlist_entry_playing')
        if not playlist_entry:
            playlist_entry = self.try_find_element_plus('playlist_entry_floating')
        if not playlist_entry:
            self.press_back()

        playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        if not playlist_entry:
            self.navigate_to_home()
            playlist_entry = self.wait_for_element_clickable_plus('playlist_entry_floating')
        playlist_entry.click()

        playlist_playing = self.wait_for_element_clickable_plus('playlist_playing')
        # can_scroll = True
        can_scroll = False
        if not playlist_playing:
            self.logger.error("Failed to find playlist playing")
            return {'error': 'Failed to find playlist playing'}

        if can_scroll:
            try:
                playing_loc = playlist_playing.location
                playing_size = playlist_playing.size
            except StaleElementReferenceException as e:
                self.logger.warning(f"Playing indicator invisible in playlist playing, {traceback.format_exc()}")
                playing_loc = None
                playing_size = None
                can_scroll = False

            # Find playlist title element
            playlist_header = self.try_find_element_plus('playlist_header')
            if not playlist_header:
                self.logger.error("Failed to find playlist header")
                return {'error': 'Failed to find playlist header'}

            title_loc = playlist_header.location
            # Calculate swipe coordinates
            start_x = playing_loc['x'] + playing_size['width'] // 2
            start_y = playing_loc['y']
            end_y = title_loc['y']

            # Swipe playing element up to title position
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            self.logger.info(f"Scrolled playlist from y={start_y} to y={end_y}")

        # Get all songs and singers
        items = self.driver.find_elements(AppiumBy.ID, self.config['elements']['playlist_item_container'])

        playlist_info = []
        for item in items:
            try:
                song = self.find_child_element(item, AppiumBy.ID, self.config['elements']['playlist_song'])
                if not song:
                    self.logger.warning("Failed to find song in playlist")
                    continue
                singer = self.find_child_element(item, AppiumBy.ID, self.config['elements']['playlist_singer'])
                info = f'{song.text}{singer.text}' if singer else song.text
                playlist_info.append(info)
            except StaleElementReferenceException as e:
                self.logger.warning(f"Error getting song/singer text, {len(items)} ")
                continue

        if not playlist_info:
            self.logger.error("No songs found in playlist")
            return {'error': 'No songs found in playlist'}

        self.logger.info(f"Found {len(playlist_info)} songs in playlist")
        return {'playlist': '\n'.join(playlist_info)}

    def change_play_mode(self, mode):
        """Change play mode
        Args:
            mode: int, 1 for single loop, -1 for random, 0 for list loop
        Returns:
            dict: mode info or error
        """
        if not self.switch_to_app():
            return {'error': 'Failed to switch to QQ Music app'}

        # Try to find playing bar
        playing_bar = self.try_find_element_plus('playing_bar')

        if not playing_bar:
            # Navigate to home and try again
            self.navigate_to_home()
            playing_bar = self.wait_for_element_clickable_plus('playing_bar')
            if not playing_bar:
                return {'error': 'Cannot find playing bar'}

        playing_bar.click()
        self.logger.info("Clicked playing bar")

        # Find play mode button
        play_mode = self.wait_for_element_clickable_plus('play_mode')
        if not play_mode:
            return {'error': 'Cannot find play mode button'}

        # Get current mode
        current_desc = play_mode.get_attribute('content-desc')
        target_desc = {
            1: "单曲循环",
            -1: "随机播放",
            0: "列表循环"
        }.get(mode)

        # Convert mode to display text
        mode_text = {
            1: "single loop",
            -1: "random",
            0: "list loop"
        }.get(mode, "unknown")

        # Click until we reach target mode if needed
        if current_desc != target_desc:
            while True:
                play_mode.click()
                time.sleep(0.5)  # Wait for mode to change
                new_desc = play_mode.get_attribute('content-desc')
                if new_desc == target_desc:
                    break

        return {'mode': mode_text}