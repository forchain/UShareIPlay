import traceback
from typing import Set, List, Optional
from datetime import datetime
from ushareiplay.core.singleton import Singleton


class InfoManager(Singleton):
    """
    信息管理器（门面）

    原 InfoManager 是一个 kitchen sink，混合了房间状态、在线用户、播放缓存、
    UI 抓取等多个职责。现在这些职责已拆分到 ushareiplay.state 下的专门模块，
    InfoManager 保留为薄门面，保持现有调用点兼容。
    """

    def __init__(self):
        """初始化信息管理器，创建/获取子模块单例"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._logger = None
        self._party_manager = None

    def __setattr__(self, name, value):
        """保留旧测试直接注入 _handler/_logger 的能力，并同步给子模块。"""
        super().__setattr__(name, value)
        if name in ('_handler', '_logger') and value is not None:
            self._propagate_injected_handler_logger()

    def _propagate_injected_handler_logger(self):
        """如果外部测试已注入 _handler/_logger，同步给已创建的子模块。"""
        handler = self.__dict__.get('_handler')
        logger = self.__dict__.get('_logger')
        if hasattr(self, '_InfoManager__room_state') and logger is not None:
            self.__room_state._logger = logger
        if hasattr(self, '_InfoManager__presence_tracker') and logger is not None:
            self.__presence_tracker._logger = logger
        if hasattr(self, '_InfoManager__playlist_state') and logger is not None:
            self.__playlist_state._logger = logger
        if hasattr(self, '_InfoManager__playback_broadcaster'):
            if handler is not None:
                self.__playback_broadcaster._soul_handler = handler
            if logger is not None:
                self.__playback_broadcaster._logger = logger
        if hasattr(self, '_InfoManager__online_list_scraper'):
            if handler is not None:
                self.__online_list_scraper._handler = handler
            if logger is not None:
                self.__online_list_scraper._logger = logger

    @property
    def _room_state(self):
        if not hasattr(self, '__room_state'):
            from ushareiplay.state.room_state import RoomState
            self.__room_state = RoomState.instance()
            self._propagate_injected_handler_logger()
        return self.__room_state

    @property
    def _presence_tracker(self):
        if not hasattr(self, '__presence_tracker'):
            from ushareiplay.state.presence_tracker import PresenceTracker
            self.__presence_tracker = PresenceTracker.instance()
            self._propagate_injected_handler_logger()
        return self.__presence_tracker

    @property
    def _playlist_state(self):
        if not hasattr(self, '__playlist_state'):
            from ushareiplay.state.playlist_state import PlaylistState
            self.__playlist_state = PlaylistState.instance()
            self._propagate_injected_handler_logger()
        return self.__playlist_state

    @property
    def _playback_broadcaster(self):
        if not hasattr(self, '__playback_broadcaster'):
            from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
            self.__playback_broadcaster = PlaybackBroadcaster.instance()
            self._propagate_injected_handler_logger()
        return self.__playback_broadcaster

    @property
    def _online_list_scraper(self):
        if not hasattr(self, '__online_list_scraper'):
            from ushareiplay.state.online_list_scraper import OnlineListScraper
            self.__online_list_scraper = OnlineListScraper.instance()
            self._propagate_injected_handler_logger()
        return self.__online_list_scraper

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def party_manager(self):
        """延迟获取 PartyManager 实例"""
        if self._party_manager is None:
            from ushareiplay.managers.party_manager import PartyManager
            self._party_manager = PartyManager.instance()
        return self._party_manager

    # ------------------------------------------------------------------
    # 兼容旧测试直接注入的内部属性
    # ------------------------------------------------------------------
    @property
    def _online_users(self):
        return self._presence_tracker._online_users

    @_online_users.setter
    def _online_users(self, value):
        self._presence_tracker._online_users = set(value) if value is not None else set()

    @property
    def _playback_info_cache(self):
        return self._playback_broadcaster._playback_info_cache

    @_playback_info_cache.setter
    def _playback_info_cache(self, value):
        self._playback_broadcaster._playback_info_cache = value

    # ------------------------------------------------------------------
    # Playlist / Player 状态（委托给 PlaylistState）
    # ------------------------------------------------------------------
    @property
    def player_name(self) -> str:
        """获取当前播放器名称"""
        return self._playlist_state.player_name

    @player_name.setter
    def player_name(self, value: str):
        """设置播放器名称"""
        self._playlist_state.player_name = value

    @property
    def current_playlist_name(self) -> str:
        """获取当前歌单名称（完整原始名称）"""
        return self._playlist_state.current_playlist_name

    @current_playlist_name.setter
    def current_playlist_name(self, value: str):
        """设置当前歌单名称"""
        self._playlist_state.current_playlist_name = value

    # ------------------------------------------------------------------
    # 在线用户（委托给 PresenceTracker）
    # ------------------------------------------------------------------
    def update_online_users(self, users: List[str]):
        """
        更新在线用户列表

        Args:
            users: 在线用户名列表
        """
        self._presence_tracker.update_online_users(users)

    def is_user_online(self, username: str) -> bool:
        """
        检查用户是否在线

        Args:
            username: 用户名

        Returns:
            bool: True 表示用户在线，False 表示不在线
        """
        return self._presence_tracker.is_user_online(username)

    def get_online_users(self) -> Set[str]:
        """
        获取所有在线用户

        Returns:
            Set[str]: 在线用户集合
        """
        return self._presence_tracker.get_online_users()

    # ------------------------------------------------------------------
    # 房间状态（委托给 RoomState）
    # ------------------------------------------------------------------
    @property
    def user_count(self) -> Optional[int]:
        """
        获取在线人数

        Returns:
            Optional[int]: 在线人数，如果未初始化则返回 None
        """
        return self._room_state.user_count

    @user_count.setter
    def user_count(self, value: int):
        """
        设置在线人数

        Args:
            value: 在线人数
        """
        # 同步 setter 只负责记录人数（上次值），不触发 UI 扫描。
        # 在线用户列表的 UI 刷新由 UserCountEvent 触发。
        self._room_state.user_count = value

    async def set_user_count(self, value: int):
        """异步设置在线人数（仅更新缓存值；UI 刷新由 UserCountEvent 负责）。"""
        if self._room_state.user_count == value:
            return
        self._room_state.user_count = value

    @property
    def focus_count(self) -> Optional[int]:
        """专注人数（与 config elements 的 key 同名；此处为缓存整型）。"""
        return self._room_state.focus_count

    @focus_count.setter
    def focus_count(self, value: int):
        self._room_state.focus_count = value

    @property
    def room_id(self) -> Optional[str]:
        """
        获取房间ID

        Returns:
            Optional[str]: 房间ID，如果未初始化则返回 None
        """
        return self._room_state.room_id

    @room_id.setter
    def room_id(self, value: str):
        """
        设置房间ID

        Args:
            value: 房间ID
        """
        self._room_state.room_id = value

    def clear(self):
        """清空在线用户列表与房间状态"""
        self._presence_tracker._online_users.clear()
        self._room_state._user_count = None
        self._room_state._focus_count = None
        self._room_state._room_id = None
        self.logger.info("Cleared online users list")

    # ------------------------------------------------------------------
    # 派对时长 / 歌单信息
    # ------------------------------------------------------------------
    def get_party_duration_info(self) -> Optional[str]:
        """
        获取派对时长信息

        Returns:
            Optional[str]: 派对时长信息，格式为 "派对开始时间: XX:XX, 持续时间: XX小时XX分钟"
                          如果派对未初始化则返回 None
        """
        try:
            if self.party_manager.init_time is None:
                return None

            init_time = self.party_manager.init_time
            current_time = datetime.now()
            duration = current_time - init_time

            # 计算小时和分钟
            total_minutes = int(duration.total_seconds() / 60)
            hours = total_minutes // 60
            minutes = total_minutes % 60

            # 格式化开始时间
            start_time_str = init_time.strftime("%H:%M")

            # 格式化持续时间
            if hours > 0:
                duration_str = f"{hours}小时{minutes}分钟"
            else:
                duration_str = f"{minutes}分钟"

            return f"{start_time_str}, {duration_str}"

        except Exception:
            self.logger.error(f"Error getting party duration info: {traceback.format_exc()}")
            return None

    def get_playlist_info(self) -> Optional[dict]:
        """
        获取当前歌单信息

        Returns:
            Optional[dict]: 歌单信息，包含 'type' (歌单类型) 和 'name' (完整歌单名称)
                          如果没有活跃歌单则返回 None
        """
        try:
            if not self._playlist_state.current_playlist_name:
                return None

            # 获取歌单类型 from music_handler.list_mode
            from ushareiplay.handlers.qq_music_handler import QQMusicHandler
            music_handler = QQMusicHandler.instance()
            playlist_type = music_handler.list_mode if music_handler else 'unknown'

            return {
                'type': playlist_type,
                'name': self._playlist_state.current_playlist_name
            }

        except Exception:
            self.logger.error(f"Error getting playlist info: {traceback.format_exc()}")
            return None

    # ------------------------------------------------------------------
    # 播放信息缓存与广播（委托给 PlaybackBroadcaster）
    # ------------------------------------------------------------------
    def update_playback_info_cache(self):
        """
        更新播放信息缓存
        获取播放信息并更新缓存
        """
        self._playback_broadcaster.update_playback_info_cache()

    def get_playback_info_cache(self) -> Optional[dict]:
        """
        获取播放信息缓存

        Returns:
            Optional[dict]: 播放信息，如果缓存未初始化则返回 None
        """
        return self._playback_broadcaster.get_playback_info_cache()

    def ensure_cached_release_date(self) -> Optional[dict]:
        return self._playback_broadcaster.ensure_cached_release_date()

    def send_playing_message(self):
        self._playback_broadcaster.send_playing_message()

    # ------------------------------------------------------------------
    # UI 抓取（委托给 OnlineListScraper）
    # ------------------------------------------------------------------
    async def refresh_online_users(self):
        """人数变化时，从在线用户列表 UI 刷新在线用户集合，并更新用户等级。"""
        await self._online_list_scraper.refresh_online_users()

    # ------------------------------------------------------------------
    # 主循环更新（委托给 PlaybackBroadcaster）
    # ------------------------------------------------------------------
    def update(self):
        """
        更新播放信息，检测变化并处理
        这个方法会在主循环中被调用
        """
        self._playback_broadcaster.update()
