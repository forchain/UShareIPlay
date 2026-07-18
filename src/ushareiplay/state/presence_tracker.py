import asyncio
import traceback
from typing import List, Set

from ushareiplay.core.singleton import Singleton


class PresenceTracker(Singleton):
    """在线用户集合与进入/离开通知。"""

    def __init__(self):
        self._logger = None
        self._online_users: Set[str] = set()

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
            from ushareiplay.managers.command_manager import CommandManager
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
