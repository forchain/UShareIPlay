"""房间包的出站端口：钩子命令持久化、消息出口、在线名单与管理状态存储。

端口只描述房间业务需要的能力；生产实现在 `adapters/`，测试替身在 `tests/fakes/`。
"""

from abc import ABC, abstractmethod
from typing import Optional, Set

from ushareiplay.modules.room.domain import HookCommand


class UserEventHookRepository(ABC):
    """用户事件钩子命令的持久化；事件类型是第一等参数。

    查询口径（single-id / alias-group）由 `registry` 按事件类型声明，
    实现必须照做。
    """

    @abstractmethod
    async def create(self, event_type: str, username: str, command: str) -> HookCommand:
        """为用户新建一条该事件类型的命令（写 canonical 主账号）。"""

    @abstractmethod
    async def get_by_username(self, event_type: str, username: str) -> list[HookCommand]:
        """该用户在此事件类型下的全部命令，按 id 升序。"""

    @abstractmethod
    async def get_all_ordered(self, event_type: str) -> list[HookCommand]:
        """全部用户的命令，按 id 升序。"""

    @abstractmethod
    async def get_by_id(self, event_type: str, command_id: int) -> Optional[HookCommand]:
        """按 id 取单条命令。"""

    @abstractmethod
    async def delete_by_id(self, event_type: str, command_id: int) -> bool:
        """按 id 删除单条命令，返回是否真的删掉了。"""

    @abstractmethod
    async def delete_all_by_username(self, event_type: str, username: str) -> int:
        """清空该用户在此事件类型下的全部命令，返回删除条数。"""


class HookCommandSink(ABC):
    """钩子命令的入队出口：交给运行时队列，由队列 drain 时执行。"""

    @abstractmethod
    async def enqueue(self, content: str, nickname: str) -> None:
        """投递一条待执行命令。"""


class PresenceQuery(ABC):
    """当前在线用户集合的只读查询。"""

    @abstractmethod
    def get_online_users(self) -> Set[str]:
        """在线用户名集合（副本）。"""

    @abstractmethod
    def is_user_online(self, username: str) -> bool:
        """该用户当前是否在线。"""


class MemoryConsolidationSink(ABC):
    """用户离开时的记忆沉淀调度。"""

    @abstractmethod
    def schedule_consolidation_user(self, username: str) -> None:
        """为某个用户安排一次记忆沉淀。"""


class RoomStateStore(ABC):
    """房间状态的跨进程持久化（预期房间 ID）。"""

    @abstractmethod
    def load_expected_party_id(self) -> Optional[str]:
        """读取上次显式设置的预期房间 ID。"""

    @abstractmethod
    def save_expected_party_id(self, party_id: Optional[str]) -> None:
        """持久化预期房间 ID。"""


class OnlineListSource(ABC):
    """从在线用户列表 UI 刷新在线用户集合。"""

    @abstractmethod
    async def refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        """按人数（可缺省）抓取在线名单；失败返回 False。"""
