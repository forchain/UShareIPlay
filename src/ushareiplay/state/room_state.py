from typing import Optional

from ushareiplay.core.singleton import Singleton


class RoomState(Singleton):
    """房间静态/半静态状态：在线人数、专注人数、房间ID。"""

    def __init__(self):
        self._logger = None
        self._user_count: Optional[int] = None
        self._focus_count: Optional[int] = None
        self._room_id: Optional[str] = None

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    @property
    def user_count(self) -> Optional[int]:
        """获取在线人数"""
        return self._user_count

    @user_count.setter
    def user_count(self, value: int):
        """设置在线人数"""
        if self._user_count != value:
            self.logger.info(f"User count updated: {self._user_count} -> {value}")
        self._user_count = value

    @property
    def focus_count(self) -> Optional[int]:
        """专注人数（与 config elements 的 key 同名；此处为缓存整型）。"""
        return self._focus_count

    @focus_count.setter
    def focus_count(self, value: int):
        if self._focus_count != value:
            self.logger.info(f"Focus count updated: {self._focus_count} -> {value}")
        self._focus_count = value

    @property
    def room_id(self) -> Optional[str]:
        """获取房间ID"""
        return self._room_id

    @room_id.setter
    def room_id(self, value: str):
        """设置房间ID"""
        if self._room_id != value:
            self.logger.info(f"Room ID updated: {self._room_id} -> {value}")
        self._room_id = value

    def clear(self):
        """清空房间状态"""
        self._user_count = None
        self._focus_count = None
        self._room_id = None
        self.logger.info("Cleared room state")
