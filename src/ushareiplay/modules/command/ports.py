"""命令包对外的端口：执行运行时、睡眠策略、客房策略、自然语言与关键字仓储。

端口只描述命令派发需要的能力，生产实现是现有的 runtime context /
`SleepManager` / `RoomState`；测试替身直接实现这些方法即可。
"""

from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional

from ushareiplay.modules.command.domain import (
    KEYWORD_MODE_SEQUENCE,
    Keyword,
    NaturalLanguageContext,
    NaturalLanguageResult,
)


class CommandRuntime(ABC):
    """命令执行期的运行时上下文：观测事件与 UI 独占会话。"""

    @abstractmethod
    def emit(self, event: str, *, ctx: Mapping[str, Any]) -> None:
        """发出一个命令生命周期事件（观测失败不得打断命令）。"""

    @abstractmethod
    def ui_session(self, reason: str):
        """返回异步上下文管理器，持有 UI 执行权直到命令结束。"""


class SleepPolicy(ABC):
    """睡眠保护策略。"""

    @abstractmethod
    def is_blocked_command(self, command: str) -> bool:
        """该命令在睡眠时段内是否应被拦截。"""


class GuestRoomPolicy(ABC):
    """他人房间（客房模式）的命令白名单策略。"""

    @property
    @abstractmethod
    def is_guest_room(self) -> bool:
        """当前是否处于他人房间。"""

    @abstractmethod
    def is_command_allowed_in_guest_room(self, prefix: str) -> bool:
        """该前缀是否在客房白名单内。"""


class NaturalLanguageResolver(ABC):
    """自然语言解析出站端口：把文本与用例构建好的提示交给 LLM。

    实现负责传输与响应校验，返回 `NaturalLanguageResult`；不可用/无法解析时返回 None。
    """

    @abstractmethod
    async def resolve(
        self, text: str, context: NaturalLanguageContext
    ) -> Optional[NaturalLanguageResult]:
        """解析一条自然语言文本。"""


class KeywordRepository(ABC):
    """关键字持久化端口；签名与既有 `KeywordDAO` 对齐，只进出领域对象。"""

    @abstractmethod
    async def create(
        self,
        keyword: str,
        command: str,
        creator_id: Optional[int] = None,
        is_public: bool = True,
        mode: str = KEYWORD_MODE_SEQUENCE,
    ) -> Keyword:
        """创建一条关键字；`creator_id=None` 表示配置关键字。"""

    @abstractmethod
    async def get_by_keyword(self, keyword: str) -> Optional[Keyword]:
        """按关键字文本查询（含创建者信息）。"""

    @abstractmethod
    async def get_by_keyword_and_username(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        """按关键字文本与创建者昵称查询。"""

    @abstractmethod
    async def find_accessible_keyword(
        self, keyword: str, username: str
    ) -> Optional[Keyword]:
        """查找该用户可执行的关键字（公开 / 创建者 / 白名单）。"""

    @abstractmethod
    async def grant_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        """把 canonical 用户 ID 加入白名单。"""

    @abstractmethod
    async def revoke_users(self, keyword: str, user_ids: list[int]) -> Optional[Keyword]:
        """把 canonical 用户 ID 移出白名单。"""

    @abstractmethod
    async def delete_by_keyword(self, keyword: str) -> bool:
        """按关键字文本删除；不存在返回 False。"""

    @abstractmethod
    async def delete_config_keywords(self) -> int:
        """删除全部配置关键字，返回删除条数。"""

    @abstractmethod
    async def update_publicity(self, keyword: str, is_public: bool) -> Optional[Keyword]:
        """更新关键字公开性；不存在返回 None。"""

    @abstractmethod
    async def list_by_creator(self, username: str) -> list[Keyword]:
        """列出某用户创建的关键字。"""

    @abstractmethod
    async def list_all(self) -> list[Keyword]:
        """列出全部关键字。"""


class KeywordCommandQueue(ABC):
    """关键字执行出口：把命令文本交回运行时消息队列。"""

    @abstractmethod
    async def enqueue(
        self, content: str, *, nickname: str, sleep_exempt: bool
    ) -> None:
        """投递一条待执行命令。"""


class KeywordConfigSource(ABC):
    """关键字预设文件（`config/keywords.yaml`）的读取口。"""

    @abstractmethod
    def load(self) -> Optional[Mapping[str, Any]]:
        """返回解析后的配置；文件不存在返回 None。"""


class UserPresence(ABC):
    """添加关键字前的在线校验。"""

    @abstractmethod
    def is_user_online(self, username: str) -> bool:
        """该昵称当前是否在线。"""


class ChatLogRecorder(ABC):
    """把 @ 群主的发言记入用户聊天日志，供记忆系统使用。"""

    @abstractmethod
    async def record(self, username: str, content: str) -> None:
        """记录一条用户发言。"""


class NaturalLanguageFallback(ABC):
    """未命中关键字时的自然语言兜底接缝。

    生产实现负责拼装播放/房间/记忆上下文并调用 #548 的 `ResolveNaturalLanguage`；
    用例只关心解析出的命令或回复文本。
    """

    @abstractmethod
    async def resolve(
        self, *, user_text: str, user_name: str, user_level: int
    ) -> Optional[NaturalLanguageResult]:
        """把一句话解析成命令/回复；解析失败返回 None。"""
