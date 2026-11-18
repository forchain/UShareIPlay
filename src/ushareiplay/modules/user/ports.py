"""用户仓储端口；语义与既有 `UserDAO` 对齐，但只进出领域对象。"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from ushareiplay.modules.user.domain import ChatLogEntry, User, UserMemory


class UserRepository(ABC):
    @abstractmethod
    async def get_or_create(self, username: str) -> User:
        """按昵称取用户（不存在则创建），并解析到 canonical。"""

    @abstractmethod
    async def get_or_create_raw(self, username: str) -> User:
        """按昵称取用户（不存在则创建），不做 canonical 解析。"""

    @abstractmethod
    async def resolve_canonical(self, user: User) -> User:
        """沿别名链解析到 canonical；断链/环时回退到传入的用户。"""

    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """按 ID 查询。"""

    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[User]:
        """按昵称查询（不创建、不解析）。"""

    @abstractmethod
    async def update_level(self, user_id: int, level: int) -> Optional[User]:
        """直接设置等级；用户不存在时返回 None。"""

    @abstractmethod
    async def update_level_if_lower(self, username: str, target_level: int) -> Optional[User]:
        """仅当当前等级低于目标等级时升级。"""

    @abstractmethod
    async def record_owner_gift(self, username: str) -> Optional[User]:
        """记录给房主的礼物：等级低于 4 时升到 4。"""

    @abstractmethod
    async def record_heat_contribution(self, username: str, heat_value: int) -> Optional[User]:
        """累加热力并按累计阈值提升等级。"""

    @abstractmethod
    async def get_identity_usernames(self, username: str) -> set[str]:
        """同一身份（canonical + 全部分身）的昵称集合，不写库。"""

    @abstractmethod
    async def is_same_identity(self, requested_username: str, observed_username: str) -> bool:
        """两个昵称是否属于同一身份。"""

    @abstractmethod
    async def get_all_avatar_usernames(self, username: str) -> set[str]:
        """canonical + 全部分身昵称集合；陌生名字会被创建。"""

    @abstractmethod
    async def get_all_associated_user_ids(self, username: str) -> list[int]:
        """同一身份所有账号的 DB ID（含原始记录、canonical 与全部分身）。"""

    @abstractmethod
    async def set_canonical(self, alias_id: int, canonical_id: int) -> User:
        """写入别名链接；别名记录必须已存在。"""


class UserMemoryRepository(ABC):
    @abstractmethod
    async def get(self, user_id: int) -> Optional[UserMemory]:
        """按 canonical 用户 ID 取长期记忆；不存在返回 None。"""

    @abstractmethod
    async def update(
        self,
        user_id: int,
        directives: list[str],
        profile: str,
        consolidated_at: datetime,
    ) -> UserMemory:
        """写入铁律区、画像与沉淀游标（不存在则创建）。"""


class ChatLogRepository(ABC):
    @abstractmethod
    async def create(self, user_id: int, content: str) -> ChatLogEntry:
        """记录一条短期聊天，返回带 ID 与时间戳的领域对象。"""

    @abstractmethod
    async def count_unconsolidated(
        self, user_id: int, since: Optional[datetime] = None
    ) -> int:
        """统计游标之后的聊天条数。"""

    @abstractmethod
    async def unconsolidated_logs(
        self,
        user_id: int,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[ChatLogEntry]:
        """按时间正序取游标之后的聊天。"""

    @abstractmethod
    async def active_user_ids_with_unconsolidated_logs(
        self, min_count: int = 1
    ) -> list[tuple[int, int]]:
        """返回 (user_id, 未沉淀条数)，仅含达到 min_count 的用户。"""


class MemoryDistiller(ABC):
    @abstractmethod
    async def distill(
        self,
        user_name: str,
        existing_directives: list[str],
        existing_profile: str,
        new_messages: list[str],
    ) -> tuple[bool, list[str], str]:
        """把新增发言蒸馏进长期记忆；失败时返回原始值且不得推进游标。"""
