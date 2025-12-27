import asyncio
import traceback
from typing import Set, List, Optional
from datetime import datetime
from ..core.singleton import Singleton


class InfoManager(Singleton):
    """
    信息管理器
    管理在线用户列表和播放器信息
    """
    
    def __init__(self):
        """初始化信息管理器"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._logger = None
        self._party_manager = None
        self._online_users: Set[str] = set()
        self._player_name: str = "Joyer"  # 默认播放器名称
        self._current_playlist_name: str = None  # 当前歌单名称（完整原始名称）
        self._playback_info_cache: Optional[dict] = None  # 播放信息缓存
        self._last_playback_info = None  # 上次的播放信息，用于检测变化
    
    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
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
            from .party_manager import PartyManager
            self._party_manager = PartyManager.instance()
        return self._party_manager
    
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
    def current_playlist_name(self) -> str:
        """获取当前歌单名称（完整原始名称）"""
        return self._current_playlist_name
    
    @current_playlist_name.setter
    def current_playlist_name(self, value: str):
        """设置当前歌单名称"""
        self._current_playlist_name = value
        self.logger.info(f"Playlist name set to: {value}")
    
    def update_online_users(self, users: List[str]):
        """
        更新在线用户列表
        
        Args:
            users: 在线用户名列表
        """
        try:
            new_users_set = set(users)
            
            # Detect users who left (were in old set but not in new set)
            if self._online_users:  # Only check if we have previous data
                users_who_left = self._online_users - new_users_set
                
                if users_who_left:
                    for username in users_who_left:
                        self.logger.critical(f"User left: {username}")
                        # Notify commands via CommandManager
                        self._notify_user_leave(username)
                
                # Detect users who entered (are in new set but not in old set)
                users_who_entered = new_users_set - self._online_users
                
                if users_who_entered:
                    for username in users_who_entered:
                        self.logger.critical(f"User entered: {username}")
                        # Notify commands via CommandManager
                        self._notify_user_enter(username)
            
            # Update the set
            self._online_users = new_users_set
            self.logger.info(f"Updated online users list: {len(self._online_users)} users")
            self.logger.debug(f"Online users: {', '.join(sorted(self._online_users))}")
        except Exception:
            self.logger.error(f"Error updating online users: {traceback.format_exc()}")
    
    def _notify_user_leave(self, username: str):
        """
        Notify all commands that a user has left
        
        Args:
            username: Username of the user who left
        """
        try:
            from .command_manager import CommandManager
            command_manager = CommandManager.instance()
            asyncio.create_task(command_manager.notify_user_leave(username))
        except Exception:
            self.logger.error(f"Error notifying user leave: {traceback.format_exc()}")
    
    def _notify_user_enter(self, username: str):
        """
        Notify all commands that a user has entered
        
        Args:
            username: Username of the user who entered
        """
        try:
            from .command_manager import CommandManager
            command_manager = CommandManager.instance()
            asyncio.create_task(command_manager.notify_user_enter(username))
        except Exception:
            self.logger.error(f"Error notifying user enter: {traceback.format_exc()}")
    
    def is_user_online(self, username: str) -> bool:
        """
        检查用户是否在线
        
        Args:
            username: 用户名
            
        Returns:
            bool: True 表示用户在线，False 表示不在线
        """
        return username in self._online_users
    
    def get_online_users(self) -> Set[str]:
        """
        获取所有在线用户
        
        Returns:
            Set[str]: 在线用户集合
        """
        return self._online_users.copy()
    
    def clear(self):
        """清空在线用户列表"""
        self._online_users.clear()
        self.logger.info("Cleared online users list")
    
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
            
            return f"派对开始时间: {start_time_str}, 持续时间: {duration_str}"
            
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
            if not self._current_playlist_name:
                return None
            
            # 获取歌单类型 from music_handler.list_mode
            from ..handlers.qq_music_handler import QQMusicHandler
            music_handler = QQMusicHandler.instance()
            playlist_type = music_handler.list_mode if music_handler else 'unknown'
            
            return {
                'type': playlist_type,
                'name': self._current_playlist_name
            }
            
        except Exception:
            self.logger.error(f"Error getting playlist info: {traceback.format_exc()}")
            return None
    
    def update_playback_info_cache(self):
        """
        更新播放信息缓存
        获取播放信息并更新缓存
        """
        try:
            # 获取播放信息
            from ..handlers.qq_music_handler import QQMusicHandler
            music_handler = QQMusicHandler.instance()
            info = music_handler.get_playback_info()
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
    
    def update(self):
        """
        更新播放信息，检测变化并处理质量检测、发送消息等
        这个方法会在主循环中被调用
        """
        try:
            # 从缓存获取播放信息
            info = self.get_playback_info_cache()
            if info is None:
                return
            
            # 检查歌曲信息是否变化
            if info != self._last_playback_info:
                self._last_playback_info = info.copy() if info else None

                # 只有在歌曲信息发生变化时才处理
                # 检查歌曲信息是否有效
                if 'error' not in info and all(key in info for key in ['song', 'singer', 'album']):
                    # 检查是否需要跳过低质量歌曲
                    from ..handlers.qq_music_handler import QQMusicHandler
                    music_handler = QQMusicHandler.instance()
                    song_skipped = music_handler.handle_song_quality_check(info)

                    # 只有在没有跳过歌曲的情况下才发送播放消息
                    if not song_skipped:
                        self.handler.send_message(
                            f"Playing {info['song']} by {info['singer']} in {info['album']}")
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
                        
        except Exception:
            self.logger.error(f"Error in info manager update: {traceback.format_exc()}")


