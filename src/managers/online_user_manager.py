import traceback
from typing import Set, List
from ..core.singleton import Singleton


class OnlineUserManager(Singleton):
    """
    在线用户管理器
    缓存当前房间内的在线用户列表，避免频繁打开UI获取
    """
    
    def __init__(self):
        """初始化在线用户管理器"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._logger = None
        self._online_users: Set[str] = set()
    
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
    
    def update_online_users(self, users: List[str]):
        """
        更新在线用户列表
        
        Args:
            users: 在线用户名列表
        """
        try:
            self._online_users = set(users)
            self.logger.info(f"Updated online users list: {len(self._online_users)} users")
            self.logger.debug(f"Online users: {', '.join(sorted(self._online_users))}")
        except Exception:
            self.logger.error(f"Error updating online users: {traceback.format_exc()}")
    
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

