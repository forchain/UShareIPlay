import re
import time
import traceback

import langdetect
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import StaleElementReferenceException

from ushareiplay.core.app_handler import AppHandler
from ushareiplay.core.singleton import Singleton


# 在导入后设置种子
langdetect.DetectorFactory.seed = 0  # 使用赋值而不是调用


class QQMusicHandler(AppHandler, Singleton):
    def __init__(self, driver, config, controller):
        super().__init__(driver, config, controller)

        self.no_skip = 0
        self.list_mode = 'unknown'
        self.play_mode_key = 'unknown'

    @staticmethod
    def play_mode_key_to_name(key: str) -> str:
        return {
            'list': '顺序播放',
            'single': '单曲循环',
            'random': '随机播放',
            'unknown': '未知',
        }.get(key, '未知')

    def _update_play_mode_key(self, new_key: str, reason: str):
        if not new_key:
            return
        if new_key not in ('unknown', 'list', 'single', 'random'):
            self.logger.warning(f"Invalid play_mode_key={new_key}, ignored (reason={reason})")
            return
        if self.play_mode_key != new_key:
            self.logger.info(
                f"play_mode_key updated: {self.play_mode_key} -> {new_key} (reason={reason})"
            )
        self.play_mode_key = new_key

    @staticmethod
    def _normalize_song_title(title: str) -> str:
        return re.sub(r"\s*-\s*$", "", (title or "").strip())

    def _read_playlist_items(self, items):
        playlist_info = []
        song_titles = []
        for item in items:
            try:
                elements = item.find_elements(AppiumBy.CLASS_NAME, 'android.widget.TextView')
                if not elements:
                    continue

                song = elements[0]
                if not song:
                    self.logger.info("Failed to find song in playlist")
                    continue
                if len(elements) < 2:
                    self.logger.info("Failed to find singer in playlist")
                    continue
                singer = elements[1]
                song_title = self._normalize_song_title(song.text)
                song_titles.append(song_title)
                if singer and singer.text:
                    # 首行可能自带末尾「 - 」；第二行常为「 - 歌手」，去重后再拼成「歌名 - 歌手」
                    singer_clean = re.sub(r"^\s*-\s*", "", (singer.text or "").strip())
                    info = f"{song_title} - {singer_clean}" if singer_clean else song_title
                else:
                    info = song.text
                playlist_info.append(info)
            except StaleElementReferenceException:
                self.logger.warning(f"Error getting song/singer text, {len(items)} ")
                continue
        return playlist_info, song_titles

    def open_favorites_entry(self, timeout: int = 10):
        """
        进入“我的 -> 收藏”页。

        已知问题：在“我的”页可能因滚动导致“收藏”入口不在可视区域；
        经验兜底：再次点击一次底部“我的”Tab可触发页面回到默认/顶部，再重试查找。

        Returns:
            None: 成功进入收藏页
            dict: 失败时返回 {'error': str}
        """
        try:
            ok = self.navigate_to_home()
            if not ok:
                return {'error': 'Cannot navigate to QQ Music home page'}

            my_nav = self.element_finder.wait_for_element_clickable('my_nav', timeout=timeout)
            if not my_nav:
                return {'error': 'Cannot find my_nav'}

            my_nav.click()
            self.logger.info("open_favorites_entry: Clicked my_nav")

            fav_entry = self.element_finder.wait_for_element_clickable('fav_entry', timeout=timeout)
            if fav_entry:
                fav_entry.click()
                self.logger.info("open_favorites_entry: Clicked fav_entry")
                return None

            # 兜底：再次点击“我的”复位页面后重试
            self.logger.warning(
                "open_favorites_entry: fav_entry not found, retrying by clicking my_nav again to reset page"
            )
            my_nav_retry = self.element_finder.wait_for_element_clickable('my_nav', timeout=timeout)
            if my_nav_retry:
                my_nav_retry.click()
                time.sleep(0.3)

            fav_entry = self.element_finder.wait_for_element_clickable('fav_entry', timeout=timeout)
            if fav_entry:
                fav_entry.click()
                self.logger.info("open_favorites_entry: Clicked fav_entry after my_nav reset")
                return None

            # 第二层兜底：回到首页再进“我的”
            self.logger.warning(
                "open_favorites_entry: fav_entry still not found, retrying with home->my_nav reset"
            )
            ok = self.navigate_to_home()
            if not ok:
                return {'error': 'Cannot navigate to QQ Music home page (retry)'}

            my_nav = self.element_finder.wait_for_element_clickable('my_nav', timeout=timeout)
            if not my_nav:
                return {'error': 'Cannot find my_nav (retry)'}
            my_nav.click()
            time.sleep(0.2)

            fav_entry = self.element_finder.wait_for_element_clickable('fav_entry', timeout=timeout)
            if not fav_entry:
                return {'error': 'Cannot find fav_entry after my_nav reset'}
            fav_entry.click()
            self.logger.info("open_favorites_entry: Clicked fav_entry after home->my_nav reset")
            return None

        except Exception as e:
            self.logger.error(f"open_favorites_entry error: {traceback.format_exc()}")
            return {'error': f'open_favorites_entry exception: {str(e)}'}

    def ensure_favorited_in_playing_page(self, timeout: int = 10) -> bool:
        """
        在播放页自动弹出后，若当前未收藏则执行收藏。

        Returns:
            bool: True 表示已收藏或收藏成功；False 表示未能确认/未能完成收藏（不应阻断主流程）
        """
        try:
            btn = self.element_finder.wait_for_element('playing_favourite', timeout=timeout)
            if not btn:
                self.logger.warning(
                    f"ensure_favorited_in_playing_page: 收藏按钮未出现(>{timeout}s)"
                )
                return False

            desc = self.element_finder.try_get_attribute(btn, 'content-desc') or ''
            if '取消收藏' in desc:
                self.logger.info("ensure_favorited_in_playing_page: 已收藏，跳过")
                return True

            clickable = self.element_finder.wait_for_element_clickable(
                'playing_favourite', timeout=timeout
            )
            if clickable:
                clickable.click()
            else:
                btn.click()
            self.logger.info(
                f"ensure_favorited_in_playing_page: 已执行收藏(当前desc={desc})"
            )
            return True
        except Exception:
            self.logger.warning(
                f"ensure_favorited_in_playing_page: 执行异常: {traceback.format_exc()}"
            )
            return False

    def hide_player(self):
        self.key_actions.press_back()
        self.logger.info("Hide player panel")
        time.sleep(1)

    def navigate_to_home(self):
        """Navigate back to home page"""
        # Keep clicking back until no more back buttons found
        n = 0
        self.key_actions.press_back()
        back_keys = ['go_back', 'minimize_screen']
        while n < 9:
            key, element = self.element_finder.wait_for_any_element(back_keys + ['home_nav'])
            if key in back_keys:
                element.click()
            elif key == 'home_nav':
                # 二次确认：命中 home_nav 后，先无等待检查是否仍有可点击返回键
                back_key, back_element = self.element_finder.try_find_any_element(back_keys)
                if back_element:
                    self.logger.info(
                        f"命中 home_nav 后仍检测到返回键 {back_key}，先点击返回再确认首页"
                    )
                    back_element.click()
                    n += 1
                    continue
                self.logger.info("Back to home page")
                return True
            else:
                self.key_actions.press_back()
                self.logger.warning("Unknown page")
                return False
            n += 1
        return False

    def get_playing_info(self):
        """Get current playing song and singer info"""
        song_element = None
        singer_element = None
        elements = self.element_finder.find_elements('first_song')
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
        song_element = self.element_finder.try_find_element('current_song')
        singer_element = self.element_finder.try_find_element('current_singer')
        if not song_element or not singer_element:
            return None
        return {
            'song': song_element.text,
            'singer': singer_element.text
        }

    def query_music(self, music_query: str):
        """Common logic for preparing music playback"""
        if not self.key_actions.switch_to_app():
            self.logger.info(f"Failed to switched to QQ Music app")
            return None
        self.logger.info(f"Switched to QQ Music app")

        key, element = self.navigator.navigate_to_element(
            'search_box',
            ['play_all', 'play_all_playlist', 'play_all_compact', 'fav_entry'],
        )
        if key == 'home_nav':
            search_entry = self.element_finder.wait_for_element('search_entry')
            if not search_entry:
                self.logger.info(f"Search entry not found")
                return None
            search_entry.click()
        elif key == 'search_box':
            clear_search = self.element_finder.try_find_element('clear_search')
            if clear_search:
                clear_search.click()
                self.logger.info(f"Clear search")

        search_box = self.element_finder.wait_for_element_clickable('search_box')
        if search_box:
            search_box.click()
            self.logger.info(f"Clicked search box")
        else:
            self.logger.error(f"failed to find search box")
            return None

        # Use clipboard operations from parent class
        self.key_actions.set_clipboard_text(music_query)
        self.key_actions.paste_text()
        return key

    def _prepare_music_playback(self, music_query):
        from_key = self.query_music(music_query)
        if not from_key:
            self.logger.error(f"Failed to query music query: {music_query}")
            playing_info = {
                'error': f"Failed to query music: {music_query}"
            }
            return playing_info

        need_select_tab = True
        if from_key == 'home_nav':
            if list_title := self.element_finder.wait_for_element('list_title'):
                if list_title.text == '单曲':
                    need_select_tab = False

        if need_select_tab:
            self.select_song_tab()

        key, element = self.element_finder.wait_for_any_element(['first_song', 'not_found'])
        if not key or key == 'not_found':
            self.logger.error(f"Failed to find music query: {music_query}")
            return {
                'error': f"not found with query {music_query}"
            }

        first_song = element
        if not first_song:
            self.logger.error(f"Failed to find first song")
            return None

        studio_version = self.element_finder.try_find_element('studio_version')
        if not studio_version:
            song_version = self.element_finder.try_find_element('song_version')
            if song_version:
                song_version.click()
                self.logger.info(f"Clicked song version")

                studio_version = self.element_finder.wait_for_element_clickable('studio_version')

        if studio_version:
            studio_version.click()
            self.logger.info("Alter to studio version")

            first_song = self.element_finder.wait_for_element('first_song')
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
            singer_text = (playing_info.get('singer') or "").strip()
            artist_count = len([x.strip() for x in singer_text.split('/') if x.strip()]) if singer_text else 0
            if (
                    playing_info.get('song', '').endswith('(Live)')
                    or (singer_text and singer_text == (playing_info.get('album') or '').strip())
                    or artist_count >= 4
            ):
                # One-time allowlist for singer-mode low-quality filters (Live / suspicious / multi-artist).
                # This preserves "play" as a temporary override without changing list_mode.
                self.no_skip += 1
        self.logger.info(f"Found playing info: {playing_info}")
        return playing_info

    def select_song_tab(self):
        """Select the 'Songs' tab in search results"""
        try:
            # Try to find song tab first
            song_tab = self.element_finder.try_find_element('song_tab')
            if not song_tab:
                # If not found, scroll music_tabs to left
                music_tabs = self.element_finder.try_find_element('music_tabs')
                if not music_tabs:
                    self.logger.error("Failed to find music tabs")
                    return False

                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location

                # Scroll to left
                self.gesture_handler.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )

                # Try to find song tab again
                song_tab = self.element_finder.try_find_element('song_tab')
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
            next_button = self.element_finder.wait_for_element_clickable('next_button')
            next_button.click()
            self.logger.info(f"Clicked next button")

            return playing_info

        except Exception as e:
            self.logger.error(f"Error playing next music: {str(e)}")
            return {
                'song': music_query,
                'singer': 'unknown'
            }

    def get_playlist_info(self):
        """Get current playlist information
        Returns:
            str: Formatted playlist info or error dict
        """
        if not self.key_actions.switch_to_app():
            self.logger.error("Cannot switch to QQ music")
            return {'error': 'Failed to switch to QQ Music app'}

        # Try to find playlist entry in playing panel first
        playlist_entry = self.element_finder.try_find_element('playlist_entry')
        if not playlist_entry:
            self.key_actions.press_back()

        playlist_entry = self.element_finder.wait_for_element_clickable('playlist_entry')
        if not playlist_entry:
            return {'error': 'Failed to find play list entry'}
        playlist_entry.click()

        detected = None
        detected_key, _ = self.element_finder.try_find_any_element(
            [
                'play_mode_list_in_playlist',
                'play_mode_single_in_playlist',
                'play_mode_random_in_playlist',
            ]
        )
        if detected_key == 'play_mode_list_in_playlist':
            detected = 'list'
        elif detected_key == 'play_mode_single_in_playlist':
            detected = 'single'
        elif detected_key == 'play_mode_random_in_playlist':
            detected = 'random'

        if detected:
            if self.play_mode_key != detected:
                self.logger.warning(
                    f"play_mode_key drift detected in playlist UI: "
                    f"recorded={self.play_mode_key}, detected={detected}"
                )
            self._update_play_mode_key(detected, reason='playlist_ui_self_heal')

        items = self.element_finder.find_elements('playlist_item_container')
        playlist_info, song_titles = self._read_playlist_items(items)

        playlist_current = self.element_finder.try_find_element('playlist_current')
        if playlist_current:
            try:
                playing_loc = playlist_current.location
                playing_size = playlist_current.size
                if len(items) > 0:
                    playlist_first = items[0]
                    start_x = playing_loc['x'] + playing_size['width'] // 2
                    start_y = playing_loc['y'] + playing_size['height'] // 2
                    end_y = playlist_first.location['y']
                    if start_y - end_y > playlist_first.size['height']:
                        self.gesture_handler.swipe(start_x, start_y, start_x, end_y, 1000)
                        items = self.element_finder.find_elements('playlist_item_container')
                        playlist_info, _ = self._read_playlist_items(items)
                        self.logger.info(f"Scrolled playlist from y={start_y} to y={end_y}")

            except StaleElementReferenceException:
                self.logger.warning("Playing indicator invisible in playlist playing")

        if not playlist_info:
            self.logger.warning("No songs found in playlist")

        self.logger.info(f"Found {len(playlist_info)} songs in playlist")
        return {'playlist': '\n'.join(playlist_info)}
