"""房间领域：房间状态（人数、房号、主客模式）与用户事件钩子命令值对象。

纯状态对象：不读写文件、不查找服务。默认主房间 ID 与「当前房号」都由构造方
注入，主客判断只做字符串比较。
"""

from dataclasses import dataclass
from typing import Callable, Optional

from ushareiplay.modules.shared.errors import DomainError


class RoomError(DomainError):
    """房间规则失败。"""


@dataclass(frozen=True)
class HookCommand:
    """一条用户事件钩子命令（持久化行在领域侧的投影）。"""

    id: int
    command: str
    owner: str


class RoomState:
    """房间静态/半静态状态：在线人数、专注人数、房间 ID、主/客房状态。"""

    def __init__(
        self,
        *,
        default_party_id: Optional[str] = None,
        current_party_id: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.default_party_id = default_party_id
        self._current_party_id = current_party_id or (lambda: None)
        self._user_count: Optional[int] = None
        self._focus_count: Optional[int] = None
        self._room_id: Optional[str] = None
        self._recommendation_enabled: Optional[bool] = None
        self._expected_party_id: Optional[str] = None
        self._is_guest_room: Optional[bool] = None

    @property
    def user_count(self) -> Optional[int]:
        return self._user_count

    @user_count.setter
    def user_count(self, value: int):
        self._user_count = value

    @property
    def focus_count(self) -> Optional[int]:
        return self._focus_count

    @focus_count.setter
    def focus_count(self, value: int):
        self._focus_count = value

    @property
    def room_id(self) -> Optional[str]:
        return self._room_id

    @room_id.setter
    def room_id(self, value: str):
        self._room_id = value

    @property
    def recommendation_enabled(self) -> Optional[bool]:
        return self._recommendation_enabled

    @recommendation_enabled.setter
    def recommendation_enabled(self, value: Optional[bool]):
        self._recommendation_enabled = value

    @property
    def expected_party_id(self) -> Optional[str]:
        return self._expected_party_id

    @expected_party_id.setter
    def expected_party_id(self, value: Optional[str]):
        self._expected_party_id = value

    @property
    def is_guest_room(self) -> bool:
        """是否处于他人房间（客房模式）。显式覆盖优先于房号比较。"""
        if self._is_guest_room is not None:
            return self._is_guest_room

        current_party_id = self.room_id or self._current_party_id()
        if current_party_id and self.default_party_id:
            return current_party_id.strip() != self.default_party_id.strip()
        return False

    @is_guest_room.setter
    def is_guest_room(self, value: Optional[bool]):
        self._is_guest_room = value

    @property
    def is_host_room(self) -> bool:
        return not self.is_guest_room

    def get_expected_party_id(self) -> Optional[str]:
        """当前应当所处的房间 ID（优先客房目标，回退配置的默认主房间）。"""
        if self.expected_party_id:
            return self.expected_party_id.strip()
        return self.default_party_id

    def adopt_host_room(self, room_id: Optional[str]) -> bool:
        """房间 ID 若就是配置中的主房间（群主转让）则恢复宿主模式。"""
        requested_id = (room_id or "").strip()
        configured_id = (self.default_party_id or "").strip()
        if not requested_id or requested_id != configured_id:
            return False
        self.promote_to_host_room(requested_id)
        return True

    def promote_to_host_room(self, room_id: Optional[str] = None) -> None:
        """把当前房间认作机器人自有房间并恢复宿主模式。"""
        self.expected_party_id = None
        if room_id:
            self.room_id = room_id
        self._is_guest_room = False

    def clear(self) -> None:
        """清空房间状态；跨模块的清理由调用方（use case）负责。"""
        self._user_count = None
        self._focus_count = None
        self._room_id = None
        self._recommendation_enabled = None
        self._is_guest_room = None
