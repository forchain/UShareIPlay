from typing import Optional

from ushareiplay.core.singleton import Singleton


class PlaylistState(Singleton):
    """播放器/歌单元数据：当前播放器名与当前歌单名。"""

    def __init__(self):
        self._logger = None
        self._player_name: str = "Joyer"  # 默认播放器名称
        self._current_playlist_name: Optional[str] = None  # 当前歌单名称（完整原始名称）

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    @property
    def player_name(self) -> str:
        """获取当前播放器名称"""
        return self._player_name

    @player_name.setter
    def player_name(self, value: str):
        """设置播放器名称"""
        self._player_name = value
        self.logger.info(f"Player name set to: {value}")

    @property
    def current_playlist_name(self) -> Optional[str]:
        """获取当前歌单名称（完整原始名称）"""
        return self._current_playlist_name

    @current_playlist_name.setter
    def current_playlist_name(self, value: str):
        """设置当前歌单名称"""
        self._current_playlist_name = value
        self.logger.info(f"Playlist name set to: {value}")
