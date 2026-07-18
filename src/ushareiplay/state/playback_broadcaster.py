import traceback
from typing import Optional

from ushareiplay.core.singleton import Singleton


class PlaybackBroadcaster(Singleton):
    """播放信息缓存、质量检查与广播发送。"""

    def __init__(self):
        self._logger = None
        self._soul_handler = None
        self._music_handler = None
        self._playback_info_cache: Optional[dict] = None  # 播放信息缓存
        self._last_playback_info = None  # 上次的播放信息，用于检测变化

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    @property
    def soul_handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._soul_handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._soul_handler = SoulHandler.instance()
        return self._soul_handler

    @property
    def music_handler(self):
        """延迟获取 QQMusicHandler 实例"""
        if self._music_handler is None:
            from ushareiplay.handlers.qq_music_handler import QQMusicHandler
            self._music_handler = QQMusicHandler.instance()
        return self._music_handler

    def update_playback_info_cache(self):
        """
        更新播放信息缓存
        获取播放信息并更新缓存
        """
        try:
            # 获取播放信息
            info = self.music_handler.get_playback_info()
            # ignore state
            info['state'] = None
            self._playback_info_cache = info
        except Exception as e:
            self.logger.error(f"Error updating playback info cache: {traceback.format_exc()}")
            # 即使出错也更新缓存，避免缓存过期
            self._playback_info_cache = {
                'error': str(e),
                'song': 'Unknown',
                'singer': 'Unknown',
                'album': 'Unknown',
                'state': None
            }

    def get_playback_info_cache(self) -> Optional[dict]:
        """
        获取播放信息缓存

        Returns:
            Optional[dict]: 播放信息，如果缓存未初始化则返回 None
        """
        return self._playback_info_cache

    def ensure_cached_release_date(self) -> Optional[dict]:
        info = self.get_playback_info_cache()
        if info is None or "error" in info:
            return info
        if info.get("release_date"):
            return info

        try:
            self.music_handler.ensure_release_date(info)
        except Exception:
            self.logger.warning(f"Failed to ensure cached release date: {traceback.format_exc()}")
        return info

    def _format_playback_message(self, info: dict) -> str:
        message = f"{info['song']} - {info['singer']} • {info['album']}"
        release_date = info.get("release_date")
        if release_date:
            message = f"{message} {release_date}"
        return message

    def send_playing_message(self):
        info = self.get_playback_info_cache()
        if info is None:
            return

        # 只有在歌曲信息发生变化时才处理
        # 检查歌曲信息是否有效
        if 'error' not in info and all(key in info for key in ['song', 'singer', 'album']):

            # 检查是否需要跳过低质量歌曲
            song_skipped = self.music_handler.handle_song_quality_check(info)

            # 只有在没有跳过歌曲的情况下才发送播放消息
            if not song_skipped:
                playback_message = self._format_playback_message(info)
                # 检查是否开启了广播
                # 运行时 self.soul_handler.config 是 soul 子配置（不是全量 config），
                # 兼容两种结构，避免读不到时错误回退为 True。
                cfg = self.soul_handler.config if isinstance(self.soul_handler.config, dict) else {}
                if 'broadcast_playing_info' in cfg:
                    broadcast_enabled = cfg.get('broadcast_playing_info', True)
                else:
                    broadcast_enabled = cfg.get('soul', {}).get('broadcast_playing_info', True)
                if not broadcast_enabled:
                    self.logger.info(f'Hidden "{playback_message}"')
                    return

                self.soul_handler.send_message(playback_message)
        else:
            # 如果歌曲信息无效，记录错误但不中断监控
            if 'error' in info:
                if info.get('session_lost', False):
                    self.logger.warning("Appium session lost, skipping music monitoring temporarily")
                    # 可以在这里添加重新连接逻辑
                else:
                    self.logger.warning(f"Failed to get song info: {info['error']}")
            else:
                self.logger.warning("Song info missing required keys")

    def update(self):
        """
        更新播放信息，检测变化并处理
        这个方法会在主循环中被调用
        """
        try:
            # 从缓存获取播放信息
            info = self.get_playback_info_cache()
            if info is None:
                return

            # 只比较播放信息的关键字段（song, singer, album），避免因为额外字段（如 online_users）导致误判
            current_playback_key = (
                info.get('song'),
                info.get('singer'),
                info.get('album')
            ) if info else None

            last_playback_key = None
            if self._last_playback_info:
                # 如果 _last_playback_info 包含额外字段，只提取基本播放信息进行比较
                last_playback_key = (
                    self._last_playback_info.get('song'),
                    self._last_playback_info.get('singer'),
                    self._last_playback_info.get('album')
                )

            # 检查歌曲信息是否变化（只比较关键字段）
            if current_playback_key != last_playback_key:
                # 记录是否是第一次初始化
                is_first_init = last_playback_key is None
                # 只保存基本播放信息，不包含额外字段
                self._last_playback_info = info.copy() if info else None

                # 第一次初始化时不广播，避免启动时刷屏
                if not is_first_init:
                    self.send_playing_message()

        except Exception:
            self.logger.error(f"Error in playback broadcaster update: {traceback.format_exc()}")
