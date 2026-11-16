import logging
from typing import Optional

from ushareiplay.core.singleton import Singleton


class PlaylistState(Singleton):
    """播放器/歌单元数据：当前播放器名与当前歌单名。"""

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._player_name: str = "Joyer"  # 默认播放器名称
        self._current_playlist_name: Optional[str] = None  # 当前歌单名称（完整原始名称）
        # Next Queue：临时点歌队列，与连续歌单上下文互不覆盖
        self._pending_next_count: int = 0
        self._next_queue_contributors: set[str] = set()

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        """获取 logger 实例"""
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("ushareiplay.state.playlist_state")
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

    # ------------------------------------------------------------------
    # Next Queue：多人 :next 累积的临时点歌队列
    # ------------------------------------------------------------------
    @property
    def pending_next_count(self) -> int:
        """尚未消费的 :next 曲目数量"""
        return self._pending_next_count

    @property
    def next_queue_contributors(self) -> set[str]:
        """往 Next Queue 点过歌的用户"""
        return self._next_queue_contributors

    def record_next(self, requester: str):
        """记录一次成功的 :next：待播数 +1，并加入贡献者。"""
        was_empty = self._pending_next_count == 0
        self._pending_next_count += 1
        self._next_queue_contributors.add(requester)
        if was_empty:
            self.logger.info(f"Next Queue started by: {requester}")

    def consume_track(self) -> None:
        """消费一次曲目切换：待播数 -1（clamp 0），归零时清空贡献者。"""
        if self._pending_next_count == 0:
            return
        self._pending_next_count -= 1
        if self._pending_next_count == 0:
            self._next_queue_contributors.clear()
            self.logger.info("Next Queue emptied")

    def clear_next_queue(self) -> None:
        """清空整个 Next Queue（新歌单已采纳时）。"""
        if self._pending_next_count == 0 and not self._next_queue_contributors:
            return
        self._pending_next_count = 0
        self._next_queue_contributors.clear()
        self.logger.info("Next Queue cleared")
