from typing import Optional

from ushareiplay.core.singleton import Singleton


class RoomState(Singleton):
    """房间静态/半静态状态：在线人数、专注人数、房间ID、主/客房状态。"""

    GUEST_ALLOWED_COMMANDS = {
        "play", "next", "fav", "skip", "pause", "vol", "mode",
        "acc", "lyrics", "singer", "album", "playlist", "radio",
        "info", "help"
    }

    def __init__(self):
        self._logger = None
        self._user_count: Optional[int] = None
        self._focus_count: Optional[int] = None
        self._room_id: Optional[str] = None
        self._recommendation_enabled: Optional[bool] = None
        self._is_guest_room: Optional[bool] = None

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    @property
    def recommendation_enabled(self) -> Optional[bool]:
        """获取房间推荐状态（True: 所有人/开放, False: 关闭推荐分发, None: 未保存/未知）"""
        return self._recommendation_enabled

    @recommendation_enabled.setter
    def recommendation_enabled(self, value: Optional[bool]):
        """设置房间推荐状态"""
        if self._recommendation_enabled != value:
            self.logger.info(f"Recommendation status updated: {self._recommendation_enabled} -> {value}")
        self._recommendation_enabled = value

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

    def _get_default_party_id(self) -> Optional[str]:
        """获取配置中的默认主房间ID"""
        try:
            from ushareiplay.handlers.soul_handler import SoulHandler
            handler = SoulHandler.instance()
            if handler and hasattr(handler, 'config') and isinstance(handler.config, dict):
                soul_cfg = handler.config.get("soul", {})
                if isinstance(soul_cfg, dict) and soul_cfg.get("default_party_id"):
                    return soul_cfg.get("default_party_id")
                return handler.config.get("default_party_id")
        except Exception:
            pass
        return None

    @property
    def is_guest_room(self) -> bool:
        """是否处于他人房间（客房模式）"""
        if self._is_guest_room is not None:
            return self._is_guest_room

        default_party_id = self._get_default_party_id()
        if self._room_id and default_party_id:
            return self._room_id.strip() != default_party_id.strip()

        return False

    @is_guest_room.setter
    def is_guest_room(self, value: Optional[bool]):
        """显式设置客房状态"""
        if self._is_guest_room != value:
            self.logger.info(f"Guest room status updated: {self._is_guest_room} -> {value}")
        self._is_guest_room = value

    @property
    def is_host_room(self) -> bool:
        """是否处于主房间（宿主模式）"""
        return not self.is_guest_room

    def is_command_allowed_in_guest_room(self, prefix: str) -> bool:
        """检查命令在他人房间（客房模式）下是否允许执行"""
        if not prefix:
            return False
        clean_prefix = prefix.lstrip(":：/／$＄").strip().lower()
        return clean_prefix in self.GUEST_ALLOWED_COMMANDS

    def clear(self):
        """清空房间状态"""
        self._user_count = None
        self._focus_count = None
        self._room_id = None
        self._recommendation_enabled = None
        self._is_guest_room = None
        self.logger.info("Cleared room state")

