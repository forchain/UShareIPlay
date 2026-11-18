"""命令包对外的端口：执行运行时、睡眠策略与客房策略。

端口只描述命令派发需要的能力，生产实现是现有的 runtime context /
`SleepManager` / `RoomState`；测试替身直接实现这些方法即可。
"""

from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional

from ushareiplay.modules.command.domain import (
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
