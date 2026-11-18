"""用户仓储端口；语义与既有 `UserDAO` 对齐，但只进出领域对象。"""

from abc import ABC, abstractmethod
from typing import Optional

from ushareiplay.modules.user.domain import User


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
