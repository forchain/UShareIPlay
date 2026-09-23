import re
import time
import traceback
from collections import deque
from typing import Optional
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.driver_decorator import with_driver_recovery


class MusicManager(Singleton):
    """
    音乐管理器 - 音乐播放的唯一公开接口。

    负责系统级播放控制（暂停/恢复/跳过/音量）、播放信息读取、以及歌曲
    质量过滤策略。QQMusicHandler 是具体的 UI adapter；命令与事件都通过
    MusicManager 访问音乐行为。
    """

    PLAYBACK_POLL_INTERVAL = 0.3  # 播放就绪轮询间隔（秒）

    # 歌曲版本后缀（如「(Live)」「（伴奏）」），比对点播目标时忽略
    _SONG_VERSION_SUFFIX_PATTERN = re.compile(r"[（(\[][^）)\]]*[）)\]]")

    # 单点（:play / :next）点播意图：待播放的点播请求队列，条目形如
    # {"song": 歌曲信息, "played": 该点播是否已播放命中过}。连续点歌时逐条排队，
    # 后一次点播不会顶掉尚未播放的前一次点播。
    _ON_DEMAND_REQUESTS_MAX = 20
    _on_demand_requests: Optional[deque] = None

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

    @staticmethod
    def _song_key(song_info) -> str:
        """歌曲名归一化：忽略空白与大小写，并去掉版本后缀，便于比对同一首歌。"""
        if not isinstance(song_info, dict):
            return ""
        song = re.sub(r"\s+", "", str(song_info.get("song") or "")).casefold()
        return MusicManager._SONG_VERSION_SUFFIX_PATTERN.sub("", song)

    @staticmethod
    def _singer_keys(song_info) -> set:
        """歌手名集合：按 '/' 拆分后归一化，Unknown 视为未知（空集）。"""
        if not isinstance(song_info, dict):
            return set()
        singer = str(song_info.get("singer") or "")
        artists = (part.strip().casefold() for part in singer.split("/"))
        return {artist for artist in artists if artist and artist != "unknown"}

    @classmethod
    def _is_same_song(cls, requested, current) -> bool:
        """是否为同一首歌：歌名归一化后相等，且歌手不冲突。

        只用歌名会让同名翻唱/重制版顶替掉点播豁免（老歌里同名曲很常见）；
        歌手任一侧未知时不据歌手否决，避免元数据缺失反而让点播的歌被跳过。
        """
        requested_song = cls._song_key(requested)
        if not requested_song or requested_song != cls._song_key(current):
            return False
        requested_singers = cls._singer_keys(requested)
        current_singers = cls._singer_keys(current)
        if not requested_singers or not current_singers:
            return True
        return bool(requested_singers & current_singers)

    def mark_on_demand(self, song_info) -> None:
        """记录用户单点（:play / :next）意图，使该歌曲豁免老歌过滤。

        由 QQMusicHandler 的显式点歌入口登记；电台与自动歌单不经过那里。
        连续点歌时逐条登记，每首点播各自保留豁免资格。
        """
        if not isinstance(song_info, dict):
            return
        if self._on_demand_requests is None:
            self._on_demand_requests = deque(maxlen=self._ON_DEMAND_REQUESTS_MAX)
        self._on_demand_requests.append({"song": dict(song_info), "played": False})

    def is_on_demand_playback(self, song_info) -> bool:
        """该歌曲是否为用户单点请求的目标。

        豁免只覆盖点播的那首歌：一旦该点播的歌曲播放过、房间又切到了别的歌，
        这条豁免即失效，电台/自动歌单播放同一首歌时重新受老歌过滤约束。

        副作用：命中时记录该点播已播放，并清理已失效的条目，因此调用方只需在
        判定“这首老歌是否该跳过”时问一次。
        """
        requests = self._on_demand_requests
        if not requests:
            return False

        matched = False
        active = []
        for entry in requests:
            if not self._is_same_song(entry.get("song"), song_info):
                # 已播放过的点播在房间换歌后作废，未播放的（含下一首点播）继续等待
                if not entry.get("played"):
                    active.append(entry)
                continue
            entry["played"] = True
            active.append(entry)
            matched = True

        self._on_demand_requests = deque(active, maxlen=self._ON_DEMAND_REQUESTS_MAX)
        return matched

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

    def wait_for_playback_ready(self, expected_song: Optional[str] = None,
                                timeout: float = 5.0,
                                settling_delay: float = 0.3) -> bool:
        """等待底层播放就绪：state=Playing 且（可选）曲目已刷新，成功后附加声卡稳定延时。

        轮询 dumpsys media_session 直至 MediaSession PlaybackState 进入 Playing；
        提供 expected_song 时拒绝上一首歌的陈旧 metadata。超时不抛异常，记录
        warning 后返回 False，由调用方兜底恢复开麦。
        """
        deadline = time.monotonic() + timeout
        while True:
            info = self.get_playback_info() or {}
            if info.get('state') == 'Playing' and self._matches_expected_song(
                    info.get('song'), expected_song):
                time.sleep(settling_delay)
                return True
            if time.monotonic() >= deadline:
                self.logger.warning(
                    "wait_for_playback_ready timed out after "
                    f"{timeout}s: state={info.get('state')}, "
                    f"song={info.get('song')}, expected={expected_song}"
                )
                return False
            time.sleep(self.PLAYBACK_POLL_INTERVAL)

    @staticmethod
    def _matches_expected_song(reported, expected_song) -> bool:
        """判断 MediaSession 上报的歌名是否已是本次点播的目标歌曲。

        按空格切词比较而非子串匹配：点歌查询常为「歌名 歌手」，上报歌名常带
        「(Live)」等后缀，两者都能命中；而子串匹配会让「:play 爱」被上一首
        「真的爱你」的陈旧 metadata 满足，导致过早开麦。
        """
        if not expected_song:
            return True
        reported = (reported or "").strip()
        expected = expected_song.strip()
        if not reported:
            return False
        if expected == reported:
            return True
        return bool(set(reported.split()) & set(expected.split()))

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
            # 用户单点（:play / :next）为强意图：点名要听的老歌不被老歌过滤跳过。
            # 电台与自动歌单播放的其他歌曲仍然遵循该规则。
            if self.is_on_demand_playback(song_info):
                self.logger.info(f"Accepting on-demand old song ({release_date} < {cutoff}): {query}")
                return False
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
