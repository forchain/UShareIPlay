import re
import time
import traceback
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.driver_decorator import with_driver_recovery


class MusicManager(Singleton):
    """
    音乐管理器 - 音乐播放的唯一公开接口。

    负责系统级播放控制（暂停/恢复/跳过/音量）、播放信息读取、以及歌曲
    质量过滤策略。QQMusicHandler 是具体的 UI adapter；命令与事件都通过
    MusicManager 访问音乐行为。
    """

    def __init__(self):
        from ushareiplay.handlers.qq_music_handler import QQMusicHandler
        self.music_handler = QQMusicHandler.instance()
        self.logger = self.music_handler.logger
        self.driver = self.music_handler.driver
        self._song_release_lookup = None

    @property
    def config(self):
        controller_config = getattr(getattr(self.music_handler, "controller", None), "config", None)
        if isinstance(controller_config, dict):
            return controller_config
        return getattr(self.music_handler, "config", {}) or {}

    @property
    def list_mode(self):
        return getattr(self.music_handler, "list_mode", "unknown")

    @list_mode.setter
    def list_mode(self, value):
        self.music_handler.list_mode = value

    @property
    def no_skip(self):
        return getattr(self.music_handler, "no_skip", 0)

    @no_skip.setter
    def no_skip(self, value):
        self.music_handler.no_skip = value

    @property
    def song_release_lookup(self):
        if self._song_release_lookup is None:
            from ushareiplay.helpers.song_release import QQMusicSongReleaseLookup
            self._song_release_lookup = QQMusicSongReleaseLookup()
        return self._song_release_lookup

    @property
    def driver_recovery_context(self):
        return getattr(self.music_handler, "driver_recovery_context", None)

    @with_driver_recovery(retry=False, op="write")
    def pause_resume(self, should_pause: bool) -> dict:
        """暂停或恢复播放 - 系统级控制"""
        action = "暂停" if should_pause else "恢复"
        self.logger.info(f"Attempting to {action} playback")
        self.driver.execute_script(
            'mobile: shell',
            {'command': 'input keyevent KEYCODE_MEDIA_PLAY_PAUSE'}
        )
        self.logger.info("Sent media play/pause key event")
        return {'action': action}

    @with_driver_recovery(retry=False, op="write")
    def skip_song(self) -> dict:
        """跳过当前歌曲 - 系统级控制"""
        self.logger.info("Attempting to skip current song")
        current_info = self.get_current_song_info()
        self.driver.execute_script(
            'mobile: shell',
            {'command': 'input keyevent KEYCODE_MEDIA_NEXT'}
        )
        self.logger.info(f"Skipped {current_info.get('song', 'Unknown')} by {current_info.get('singer', 'Unknown')}")
        return {
            'song': current_info.get('song', 'Unknown'),
            'singer': current_info.get('singer', 'Unknown')
        }

    @with_driver_recovery(op="read")
    def get_current_song_info(self) -> dict:
        """获取当前播放歌曲信息 - 系统级获取"""
        result = self.driver.execute_script(
            'mobile: shell',
            {'command': 'dumpsys media_session'}
        )

        metadata = {}
        state = "Unknown"

        if not result:
            self.logger.error("Failed to get playback information")
            return {'error': 'Failed to get playback information'}

        meta_match = re.search(r'metadata: size=\d+, description=(.*?)(?=\n)', result)
        if meta_match:
            meta_parts = meta_match.group(1).split(', ')
            if len(meta_parts) >= 3:
                metadata = {
                    'song': meta_parts[0],
                    'singer': meta_parts[1],
                    'album': meta_parts[2]
                }

        state_match = re.search(r'state=PlaybackState {state=(\d+)', result)
        if state_match:
            state_code = int(state_match.group(1))
            state = {
                0: "None", 1: "Stopped", 2: "Paused", 3: "Playing",
                4: "Fast Forwarding", 5: "Rewinding", 6: "Buffering",
                7: "Error", 8: "Connecting", 9: "Skipping to Next",
                10: "Skipping to Previous", 11: "Skipping to Queue Item"
            }.get(state_code, "Unknown")

        return {
            'song': metadata.get('song', 'Unknown'),
            'singer': metadata.get('singer', 'Unknown'),
            'album': metadata.get('album', 'Unknown'),
            'state': state
        }

    def get_playback_info(self) -> dict:
        """Public alias for get_current_song_info, used by commands and broadcaster."""
        return self.get_current_song_info()

    @with_driver_recovery
    def get_volume_level(self) -> int:
        """Get current volume level - system level"""
        result = self.driver.execute_script(
            'mobile: shell',
            {'command': 'dumpsys audio'}
        )

        if result and isinstance(result, str):
            parts = result.split('- STREAM_MUSIC:')
            if len(parts) > 1:
                match = re.search(r'streamVolume:(\d+)', parts[1])
                if match:
                    volume = int(match.group(1))
                    volume = max(0, min(15, volume))
                    self.logger.info(f"Current volume: {volume}")
                    return volume

        self.logger.warning("Could not parse volume level, using default value 0")
        return 0

    @with_driver_recovery
    def adjust_volume(self, target_volume: int = None) -> dict:
        """Adjust volume to specified level - system level control"""
        if target_volume is None:
            current_volume = self.get_volume_level()
            if current_volume is None:
                return {'error': 'Failed to get current volume level'}
            return {'volume': current_volume, 'current': True}

        if not isinstance(target_volume, int) or target_volume < 0 or target_volume > 15:
            return {'error': f'Invalid target volume: {target_volume}. Must be integer between 0-15'}

        current_volume = self.get_volume_level()
        if current_volume is None:
            return {'error': 'Failed to get current volume level'}

        delta = target_volume - current_volume
        if delta == 0:
            return {'volume': current_volume}

        times = abs(delta)
        action = self.music_handler.key_actions.press_volume_down if delta < 0 else self.music_handler.key_actions.press_volume_up
        self.logger.info(f"{'Decreasing' if delta < 0 else 'Increasing'} volume by {times} steps")
        for i in range(times):
            action()
            self.logger.info(f"{'Decreased' if delta < 0 else 'Increased'} volume ({i + 1}/{times})")

        final_volume = self.get_volume_level()
        if final_volume is None:
            final_volume = current_volume
        self.logger.info(f"Adjusted volume to {final_volume}")
        return {'volume': final_volume, 'delta': delta}

    # ------------------------------------------------------------------
    # Quality policy
    # ------------------------------------------------------------------

    def _old_song_filter_config(self) -> dict:
        return self.config.get("old_song_filter", {})

    def _is_old_song_whitelisted_artist(self, singer: str, config: dict) -> bool:
        whitelist = {
            str(artist).strip()
            for artist in config.get("artist_whitelist", [])
            if str(artist).strip()
        }
        if not whitelist or not singer:
            return False
        artists = {artist.strip() for artist in singer.split("/") if artist.strip()}
        return bool(artists & whitelist)

    def ensure_release_date(self, song_info: dict) -> None:
        if not isinstance(song_info, dict) or song_info.get("release_date"):
            return

        song = song_info.get("song", "")
        singer = song_info.get("singer", "")
        album = song_info.get("album", "")
        if not song:
            return

        query = " ".join(part for part in [song, singer, album] if part).strip()
        try:
            from ushareiplay.helpers.song_release import parse_release_date
            release_date = parse_release_date(self.song_release_lookup.get_release_date(query))
        except Exception as exc:
            self.logger.warning(f"Failed to query song release date for {query}: {exc}")
            return

        if release_date:
            song_info["release_date"] = release_date.isoformat()

    def _is_old_song(self, song: str, singer: str = "", album: str = "", song_info: dict = None) -> bool:
        config = self._old_song_filter_config()
        if not config.get("enabled", True):
            return False

        from ushareiplay.helpers.song_release import parse_release_date
        cutoff = parse_release_date(config.get("cutoff_date") or "2000-01-01")
        if not cutoff or not song:
            return False

        if song_info is None:
            song_info = {"song": song, "singer": singer, "album": album}

        self.ensure_release_date(song_info)
        release_date = parse_release_date(song_info.get("release_date"))
        query = " ".join(part for part in [song, singer, album] if part).strip()
        if not release_date:
            self.logger.info(f"Release date unknown for {query}, accepting song")
            return False

        if self._is_old_song_whitelisted_artist(singer, config):
            self.logger.info(f"Accepting old song for whitelisted artist: {query}")
            return False

        if release_date < cutoff:
            self.logger.info(f"Skipping old song ({release_date} < {cutoff}): {query}")
            return True
        return False

    def should_skip_low_quality_song(self, song_info):
        """检查是否应该跳过低质量歌曲"""
        try:
            song = song_info.get('song', '')
            singer = song_info.get('singer', '')
            album = song_info.get('album', '')

            if self._is_old_song(song, singer, album, song_info):
                return True

            if 'DJ' in song or 'Remix' in song:
                self.logger.info(f"Skipping DJ/Remix song: {song}")
                return True

            if self.list_mode == 'singer':
                singer_text = (singer or "").strip()
                artist_count = len([x.strip() for x in singer_text.split('/') if x.strip()]) if singer_text else 0
                if artist_count >= 4:
                    if self.no_skip > 0:
                        self.no_skip -= 1
                        self.logger.info(
                            f"Allowing multi-artist song (remaining skips: {self.no_skip}): {song} - {singer_text}"
                        )
                        return False
                    self.logger.info(f"Skipping multi-artist song (>=4): {song} - {singer_text}")
                    return True

                if song.endswith('(Live)'):
                    if self.no_skip > 0:
                        self.no_skip -= 1
                        self.logger.info(f"Allowing Live song (remaining skips: {self.no_skip}): {song}")
                        return False
                    self.logger.info(f"Skipping Live song (no skips left): {song}")
                    return True

            return False
        except Exception:
            self.logger.error(f"Error checking if should skip song: {traceback.format_exc()}")
            return False

    def handle_song_quality_check(self, song_info):
        """处理歌曲质量检查和跳过逻辑"""
        try:
            if self.should_skip_low_quality_song(song_info):
                self.skip_song()
                self.logger.info(f"Skipped low quality song: {song_info.get('song', 'Unknown')}")
                return True
            return False
        except Exception:
            self.logger.error(f"Error handling song quality check: {traceback.format_exc()}")
            return False
