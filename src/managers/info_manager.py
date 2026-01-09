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
        self._user_count: Optional[int] = None  # 在线人数
        self._last_user_count: Optional[int] = None  # 上次的在线人数，用于检测变化
        self._room_id: Optional[str] = None  # 房间ID
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

    @property
    def user_count(self) -> Optional[int]:
        """
        获取在线人数
        
        Returns:
            Optional[int]: 在线人数，如果未初始化则返回 None
        """
        return self._user_count

    @user_count.setter
    def user_count(self, value: int):
        """
        设置在线人数
        
        Args:
            value: 在线人数
        """
        if self._user_count != value:
            self.logger.info(f"User count updated: {self._user_count} -> {value}")
        self._user_count = value

    @property
    def room_id(self) -> Optional[str]:
        """
        获取房间ID
        
        Returns:
            Optional[str]: 房间ID，如果未初始化则返回 None
        """
        return self._room_id

    @room_id.setter
    def room_id(self, value: str):
        """
        设置房间ID
        
        Args:
            value: 房间ID
        """
        if self._room_id != value:
            self.logger.info(f"Room ID updated: {self._room_id} -> {value}")
        self._room_id = value

    def clear(self):
        """清空在线用户列表"""
        self._online_users.clear()
        self._user_count = None
        self._room_id = None
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

    def send_playing_message(self):
        info = self.get_playback_info_cache()
        if info is None:
            return

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

    def check_and_update_user_count(self):
        """
        检查并更新在线用户人数，如果人数变化则更新在线用户列表和用户等级
        这个方法会在主循环中被调用
        """
        try:
            # 检查用户人数是否变化
            current_count = self._user_count
            if current_count is None:
                return
            
            if current_count == self._last_user_count:
                return
            
            self.logger.info(f"User count changed: {self._last_user_count} -> {current_count}")
            self._last_user_count = current_count
            
            # 点击 user_count 元素打开在线用户列表
            user_count_elem = self.handler.try_find_element_plus('user_count', log=False)
            if not user_count_elem:
                return
            
            user_count_elem.click()
            self.logger.info("Clicked user count element")
            
            # 等待在线用户列表容器出现
            online_container = self.handler.wait_for_element_plus('online_users')
            if not online_container:
                self.logger.error("Online users container not found")
                return
            
            # 解析目标人数
            target_count = current_count
            
            all_online_user_names = set()
            prev_size = 0
            no_new_rounds = 0
            max_no_new_rounds = 2
            max_swipes = 50
            
            # 预计算容器内滑动坐标：手指向上滑（列表向上滚动）
            try:
                loc = online_container.location
                size = online_container.size
                left = int(loc["x"])
                top = int(loc["y"])
                width = int(size["width"])
                height = int(size["height"])
                
                swipe_x = left + int(width * 0.5)
                start_y = top + int(height * 0.8)
                end_y = top + int(height * 0.2)
            except Exception:
                self.logger.warning("Failed to compute container swipe coordinates, fallback to default swipe")
                swipe_x = None
                start_y = None
                end_y = None
            
            for swipe_idx in range(max_swipes + 1):
                # 采集当前可见的用户容器
                visible_containers = self.handler.find_child_elements_plus(online_container, 'user_container')
                if visible_containers:
                    for container in visible_containers:
                        try:
                            # 获取容器内的用户名
                            user_elem = self.handler.find_child_element_plus(container, 'online_user')
                            if not user_elem:
                                continue
                            
                            username = user_elem.text
                            if not username:
                                continue
                            
                            # 如果是新用户，处理关注状态和等级更新
                            if username not in all_online_user_names:
                                all_online_user_names.add(username)
                                
                                # 获取关注状态
                                follow_state_elem = self.handler.find_child_element_plus(container, 'follow_state')
                                follow_state = follow_state_elem.text if follow_state_elem else None
                                
                                # 根据关注状态更新用户等级
                                from ..dal.user_dao import UserDAO
                                
                                async def update_user_level():
                                    try:
                                        # 确保用户存在
                                        user = await UserDAO.get_or_create(username)
                                        
                                        # 根据关注状态更新等级
                                        if follow_state:
                                            if "密友" in follow_state:
                                                await UserDAO.update_level_if_lower(username, 3)
                                            elif "我关注的" in follow_state:
                                                await UserDAO.update_level_if_lower(username, 2)
                                            elif "关注了我" in follow_state:
                                                await UserDAO.update_level_if_lower(username, 1)
                                        # 如果没有关注状态，等级保持为 0（默认值）
                                    except Exception as e:
                                        self.logger.error(f"Error updating user level for {username}: {str(e)}")
                                
                                # 异步执行等级更新
                                asyncio.create_task(update_user_level())
                        except Exception:
                            continue
                
                # 停止条件 1：到底提示出现
                try:
                    no_more = self.handler.try_find_element_plus('no_more_data', log=False)
                    if no_more and no_more.is_displayed():
                        self.logger.info("Detected no_more_data, stop scrolling online users.")
                        break
                except Exception:
                    # ignore detection errors, continue scrolling with other stop conditions
                    pass
                
                # 停止条件 2：已收集人数达到目标人数（更快结束）
                if target_count is not None and len(all_online_user_names) >= target_count:
                    self.logger.info(
                        f"Collected {len(all_online_user_names)}/{target_count} users, stop scrolling."
                    )
                    break
                
                # 停止条件 3：连续多轮无新增（兜底）
                if len(all_online_user_names) == prev_size:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0
                    prev_size = len(all_online_user_names)
                
                if no_new_rounds >= max_no_new_rounds:
                    self.logger.info(
                        f"No new users found for {no_new_rounds} rounds, stop scrolling."
                    )
                    break
                
                # 最后一次循环不再滑动（max_swipes 达到）
                if swipe_idx >= max_swipes:
                    self.logger.info("Reached max_swipes, stop scrolling online users.")
                    break
                
                # 执行一次上滑
                try:
                    if swipe_x is not None:
                        ok = self.handler._perform_swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=400)
                        if not ok:
                            self.logger.warning("Swipe failed, stop scrolling online users.")
                            break
                    else:
                        # 兼容兜底：使用 driver.swipe 做一次中等幅度上滑
                        self.handler.driver.swipe(500, 1500, 500, 800, 600)
                except Exception as e:
                    self.logger.error(f"Error during swipe operation: {str(e)}")
                    break
                
                # 等待列表加载稳定
                try:
                    import time
                    time.sleep(0.35)
                except Exception:
                    pass
            
            # 更新在线用户列表
            self.update_online_users(list(all_online_user_names))
            
            # 关闭在线用户列表
            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.logger.info('Hide online users dialog')
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)
        
        except Exception:
            self.logger.error(f"Error checking user count: {traceback.format_exc()}")

    def update(self):
        """
        更新播放信息和在线用户信息，检测变化并处理
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
                self.send_playing_message()

        except Exception:
            self.logger.error(f"Error in info manager update: {traceback.format_exc()}")
