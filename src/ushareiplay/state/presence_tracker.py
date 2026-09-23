import asyncio
import time
import traceback
from typing import Dict, List, Set

from ushareiplay.core.singleton import Singleton


class PresenceTracker(Singleton):
    """在线用户集合与进入/离开通知。"""

    def __init__(self):
        self._logger = None
        self._online_users: Set[str] = set()
        self._recent_enters: Dict[str, float] = {}
        self._recent_returns: Dict[str, float] = {}

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    def update_online_users(self, users: List[str]):
        """
        更新在线用户列表

        Args:
            users: 在线用户名列表
        """
        try:
            prev_users_set = self._online_users
            new_users_set = set(users)

            # Detect users who left (were in old set but not in new set)
            users_who_left = set()
            users_who_entered = set()
            if prev_users_set:  # Only check if we have previous data
                users_who_left = prev_users_set - new_users_set

                if users_who_left:
                    for username in users_who_left:
                        self.logger.critical(f"User left: {username}")
                        # Notify commands via CommandManager
                        self._notify_user_leave(username)

                # Detect users who entered (are in new set but not in old set)
                users_who_entered = new_users_set - prev_users_set

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
            from ushareiplay.managers.command_manager import CommandManager
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
            self._recent_enters[username] = time.time()
            from ushareiplay.managers.command_manager import CommandManager
            command_manager = CommandManager.instance()
            asyncio.create_task(command_manager.notify_user_enter(username))
        except Exception:
            self.logger.error(f"Error notifying user enter: {traceback.format_exc()}")

    def was_recently_entered(self, username: str, window_seconds: float = 30.0) -> bool:
        """检查用户是否在最近 window_seconds 秒内刚进入房间（防止新进入房间时附带的入场消息误触发 return）"""
        now = time.time()
        for name, ts in list(self._recent_enters.items()):
            if now - ts > window_seconds:
                self._recent_enters.pop(name, None)
            elif name == username or name.strip() == username.strip():
                return True
        return False

    def should_trigger_return(self, username: str, debounce_seconds: float = 10.0) -> bool:
        """
        判断是否应该触发 return 事件：
        - 若在线用户列表已初始化且非空，而该用户不在其中，说明该用户此前不在房间内（属于全新进入房间，由在线人数变更及 UserCountEvent 触发 enter），不应触发 return。
        - 若该用户刚触发过 enter（如 30 秒内进入房间），其入场消息对应的是 enter 事件，不重复触发 return。
        - 若 10 秒内已触发过该用户的 return（如 follower 横幅与聊天室消息并发出现），进行防抖忽略。
        """
        if self._online_users and not self.is_user_online(username):
            return False

        if self.was_recently_entered(username):
            return False

        now = time.time()
        for name, ts in list(self._recent_returns.items()):
            if now - ts > debounce_seconds:
                self._recent_returns.pop(name, None)
            elif name == username or name.strip() == username.strip():
                return False

        return True

    def record_return(self, username: str):
        """记录用户返回时间，用于防抖"""
        self._recent_returns[username] = time.time()

    def is_user_online(self, username: str) -> bool:
        """
        检查用户是否在线

        Args:
            username: 用户名

        Returns:
            bool: True 表示用户在线，False 表示不在线
        """
        if username in self._online_users:
            return True
        clean_name = username.strip()
        for u in self._online_users:
            if clean_name == u.strip():
                return True
        return False

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
        self._recent_enters.clear()
        self._recent_returns.clear()
        self.logger.info("Cleared online users list")
