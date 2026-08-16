import json
from pathlib import Path
from typing import Optional

from ushareiplay.core.singleton import Singleton


class RoomState(Singleton):
    """房间静态/半静态状态：在线人数、专注人数、房间ID、主/客房状态。"""

    GUEST_ALLOWED_COMMANDS = {
        "play", "next", "fav", "skip", "pause", "vol", "mode",
        "acc", "lyrics", "singer", "album", "playlist", "radio",
        "info", "help", "room", "mic", "say"
    }

    def __init__(self):
        self._logger = None
        self._user_count: Optional[int] = None
        self._focus_count: Optional[int] = None
        self._room_id: Optional[str] = None
        self._recommendation_enabled: Optional[bool] = None
        self._is_guest_room: Optional[bool] = None
        self._expected_party_id: Optional[str] = self._load_persisted_expected_party_id()

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

    def _get_state_file_path(self) -> Path:
        return Path("data/room_state.json")

    def _load_persisted_expected_party_id(self) -> Optional[str]:
        try:
            state_file = self._get_state_file_path()
            if state_file.exists():
                data = json.loads(state_file.read_text(encoding="utf-8"))
                return data.get("expected_party_id")
        except Exception:
            pass
        return None

    def _save_persisted_expected_party_id(self, party_id: Optional[str]):
        try:
            state_file = self._get_state_file_path()
            state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {"expected_party_id": party_id}
            state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    @property
    def expected_party_id(self) -> Optional[str]:
        """获取显式设置的预期房间ID"""
        return self._expected_party_id

    @expected_party_id.setter
    def expected_party_id(self, value: Optional[str]):
        """设置并持久化预期房间ID"""
        if self._expected_party_id != value:
            self.logger.info(f"Expected party ID updated: {self._expected_party_id} -> {value}")
        self._expected_party_id = value
        self._save_persisted_expected_party_id(value)

    def get_expected_party_id(self) -> Optional[str]:
        """获取当前应当所处的房间ID（优先返回客房目标ID，回退为配置的默认主房间ID）"""
        if self._expected_party_id:
            return self._expected_party_id.strip()
        return self._get_default_party_id()

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
        current_party_id = self._room_id
        if not current_party_id:
            try:
                from ushareiplay.handlers.soul_handler import SoulHandler
                if SoulHandler.is_initialized():
                    current_party_id = SoulHandler.instance().party_id
            except Exception:
                pass

        if current_party_id and default_party_id:
            return current_party_id.strip() != default_party_id.strip()

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

