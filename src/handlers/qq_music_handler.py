import time
import traceback

import langdetect
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import StaleElementReferenceException

from ..core.app_handler import AppHandler
from ..core.singleton import Singleton

# 在导入后设置种子
langdetect.DetectorFactory.seed = 0  # 使用赋值而不是调用


class QQMusicHandler(AppHandler, Singleton):
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
        self.press_back()
        while n < 9:
            key, element = self.wait_for_any_element_plus(['go_back', 'minimize_screen', 'home_nav'])
            if key == 'go_back' or key == 'minimize_screen':
                element.click()
            elif key == 'home_nav':
                self.press_back()
                self.logger.info("Back to home page")
                return True
            else:
                self.press_back()
                self.logger.warning("Unknown page")
                return False
            n += 1
        return False

    def get_playing_info(self):
        """Get current playing song and singer info"""
        song_element = None
        singer_element = None
        elements = self.find_elements_plus('first_song')
        if elements:
            song_element = elements[0]
            if len(elements) > 1:
                singer_element = elements[1]
        if not song_element:
            return {
                "song": "Unknown",
                "singer": "Unknown",
                "album": "Unknown",
            }
        song = song_element.text
        if not singer_element:
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
            return None
        self.logger.info(f"Switched to QQ Music app")

        key, element = self.navigate_to_element('search_box',
                                                ['play_all', 'play_all_singer', 'play_all_playlist'])
        if key == 'home_nav':
            search_entry = self.wait_for_element_plus('search_entry')
            if not search_entry:
                self.logger.info(f"Search entry not found")
                return None
            search_entry.click()
        elif key == 'search_box':
            clear_search = self.try_find_element_plus('clear_search')
            if clear_search:
                clear_search.click()
                self.logger.info(f"Clear search")

        search_box = self.wait_for_element_clickable_plus('search_box')
        if search_box:
            search_box.click()
            self.logger.info(f"Clicked search box")
        else:
            self.logger.error(f"failed to find search box")
            return None

        # Use clipboard operations from parent class
        self.set_clipboard_text(music_query)
        self.paste_text()
        return key

    def _prepare_music_playback(self, music_query):
        from_key = self.query_music(music_query)
        if not from_key:
            self.logger.error(f"Failed to query music query: {music_query}")
            playing_info = {
                'error': f"Failed to query music: {music_query}"
            }
            return playing_info

        if from_key != 'home_nav':
            self.select_song_tab()

        first_song = self.wait_for_element_plus('first_song')
        if not first_song:
            self.logger.error(f"Failed to find first song")
            return None

        song_version = self.try_find_element_plus('song_version')
        if song_version:
            song_version.click()
            self.logger.info(f"Clicked song version")

            studio_version = self.wait_for_element_clickable_plus('studio_version')
            if studio_version:
                studio_version.click()
                self.logger.info("Alter to studio version")

                first_song = self.wait_for_element_plus('first_song')
                if not first_song:
                    self.logger.error(f"Failed to find first song")
                    return None

        playing_info = self.get_playing_info()
        if not playing_info:
            self.logger.warning(f"No playing info found for query: {music_query}")
            playing_info = {
                'error': f"No playing info found for query: {music_query}"
            }
            return playing_info

        if self.list_mode == 'singer':
            if playing_info['song'].endswith('(Live)') or (
                    playing_info['singer'] and playing_info['singer'] == playing_info['album']):
                self.no_skip += 1
        self.logger.info(f"Found playing info: {playing_info}")
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

    def play_next(self, music_query):
        """Search and play next music"""
        try:
            playing_info = self._prepare_music_playback(music_query)
            if 'error' in playing_info:
                self.logger.error(f'Failed to add music {music_query} to playlist')
                return playing_info

            # Click next button
            next_button = self.wait_for_element_clickable_plus('next_button')
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
        """Skip to next song - delegates to MusicManager"""
        try:
            # 使用 MusicManager 的系统级跳过功能
            from ..managers.music_manager import MusicManager
            music_manager = MusicManager.instance()
            return music_manager.skip_song()

        except Exception as e:
            self.logger.error(f"Error skipping song: {traceback.format_exc()}")
            return {
                'song': 'Unknown',
                'singer': 'Unknown'
            }

    def should_skip_low_quality_song(self, song_info):
        """
        检查是否应该跳过低质量歌曲
        Args:
            song_info: dict, 包含歌曲信息的字典 {'song': str, 'singer': str, 'album': str}
        Returns:
            bool: True if should skip, False otherwise
        """
        try:
            song = song_info.get('song', '')
            singer = song_info.get('singer', '')
            album = song_info.get('album', '')

            # 检查是否包含 DJ 或 Remix
            if 'DJ' in song or 'Remix' in song:
                self.logger.info(f"Skipping DJ/Remix song: {song}")
                return True

            # 针对歌手模式的特殊处理
            if self.list_mode == 'singer':
                # 检查是否是 Live 版本
                if song.endswith('(Live)'):
                    if self.no_skip > 0:
                        self.no_skip -= 1
                        self.logger.info(f"Allowing Live song (remaining skips: {self.no_skip}): {song}")
                        return False
                    else:
                        self.logger.info(f"Skipping Live song (no skips left): {song}")
                        return True

            return False

        except Exception as e:
            self.logger.error(f"Error checking if should skip song: {traceback.format_exc()}")
            return False

    def handle_song_quality_check(self, song_info):
        """
        处理歌曲质量检查和跳过逻辑
        Args:
            song_info: dict, 包含歌曲信息的字典
        Returns:
            bool: True if song was skipped, False otherwise
        """
        try:
            if self.should_skip_low_quality_song(song_info):
                skip_result = self.skip_song()
                self.logger.info(f"Skipped low quality song: {song_info.get('song', 'Unknown')}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error handling song quality check: {traceback.format_exc()}")
            return False

    def get_volume_level(self):
        """Get current volume level - delegates to MusicManager"""
        try:
            # 使用 MusicManager 的系统级音量获取功能
            from ..managers.music_manager import MusicManager
            music_manager = MusicManager.instance()
            return music_manager.get_volume_level()
        except Exception as e:
            self.logger.error(f"Error getting volume level: {str(e)}")
            return 0

    def get_playback_info(self):
        """Get current playback information - delegates to MusicManager"""
        try:
            # 使用 MusicManager 的系统级播放信息获取功能
            from ..managers.music_manager import MusicManager
            music_manager = MusicManager.instance()
            return music_manager.get_current_song_info()
        except Exception as e:
            self.logger.error(f"Error getting playback info: {traceback.format_exc()}")
            return {
                'song': 'Unknown',
                'singer': 'Unknown',
                'album': 'Unknown',
                'state': 'Unknown'
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
        playlist_entry = self.try_find_element_plus('playlist_entry')
        if not playlist_entry:
            self.press_back()

        playlist_entry = self.wait_for_element_clickable_plus('playlist_entry')
        if not playlist_entry:
            return {'error': 'Failed to find play list entry'}
        playlist_entry.click()

        playlist_current = self.wait_for_element_clickable_plus('playlist_current')
        if not playlist_current:
            self.logger.error("Failed to find playlist playing")
            return {'error': 'Failed to find playlist playing'}

        playlist_info = []
        playlist_first = self.driver.find_elements(AppiumBy.XPATH, self.config['elements']['playlist_first'])
        if len(playlist_first) > 0:
            first_song = playlist_first[0].text
            first_singer = playlist_first[1].text if len(playlist_first) > 1 else ''
            info = f'{first_song}{first_singer}'
            playlist_info.append(info)

        can_scroll = True
        try:
            playing_loc = playlist_current.location
            playing_size = playlist_current.size
        except StaleElementReferenceException as e:
            self.logger.warning(f"Playing indicator invisible in playlist playing, {traceback.format_exc()}")
            playing_loc = None
            playing_size = None
            can_scroll = False

        if can_scroll:
            # Find playlist title element
            playlist_header = self.try_find_element_plus('playlist_header')
            if not playlist_header:
                self.logger.error("Failed to find playlist header")
                return {'error': 'Failed to find playlist header'}

            title_loc = playlist_header.location
            title_size = playlist_header.size
            # Calculate swipe coordinates
            start_x = playing_loc['x'] + playing_size['width'] // 2
            start_y = playing_loc['y']
            end_y = title_loc['y']
            # end_y = title_loc['y'] + 3 * title_size['height']

            # Swipe playing element up to title position
            self.driver.swipe(start_x, start_y, start_x, end_y, 1000)
            self.logger.info(f"Scrolled playlist from y={start_y} to y={end_y}")

        # Get all songs and singers
        items = self.driver.find_elements(AppiumBy.XPATH, self.config['elements']['playlist_item_container'])

        for item in items:
            try:
                elements = self.find_child_elements(item, AppiumBy.CLASS_NAME, 'android.widget.TextView')
                if not elements:
                    self.logger.warning("Failed to find song in playlist")
                    continue

                song = elements[0]
                if not song:
                    self.logger.warning("Failed to find song in playlist")
                    continue
                if len(elements) < 2:
                    self.logger.warning("Failed to find singer in playlist")
                    continue
                singer = elements[1]
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
