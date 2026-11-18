"""定时器出站端口：持久化仓储与到点消息出口。"""

from abc import ABC, abstractmethod
from datetime import datetime

from ushareiplay.modules.timer.domain import Timer


class TimerMessageSink(ABC):
    """到点定时器消息的出站出口：交给队列，由运行时按普通消息执行。"""

    @abstractmethod
    async def enqueue(
        self, content: str, *, nickname: str = "Timer", sleep_exempt: bool = True
    ) -> None:
        """投递一条定时器消息。"""


class TimerRepository(ABC):
    @abstractmethod
    async def prepare(self) -> None:
        """启动前的一次性持久化准备（清洗历史数据、迁移遗留文件）；须可重复调用。"""

    @abstractmethod
    async def create(
        self,
        key: str,
        message: str,
        target_time: str,
        repeat: bool = False,
        enabled: bool = True,
        next_trigger: datetime | None = None,
    ) -> Timer:
        """创建定时器。"""

    @abstractmethod
    async def get_or_create(self, key: str, defaults: dict) -> tuple[Timer, bool]:
        """按 key 取定时器，不存在则用 defaults 创建；返回 (定时器, 是否新建)。"""

    @abstractmethod
    async def get_by_key(self, key: str) -> Timer | None:
        """按业务 key 查询。"""

    @abstractmethod
    async def list_all(self) -> list[Timer]:
        """列出全部定时器。"""

    @abstractmethod
    async def update_next_trigger(self, key: str, next_trigger: datetime) -> bool:
        """更新下次触发时间；key 不存在时返回 False。"""

    @abstractmethod
    async def update_enabled(self, key: str, enabled: bool) -> bool:
        """启停定时器；key 不存在时返回 False。"""

    @abstractmethod
    async def delete_by_key(self, key: str) -> bool:
        """按业务 key 删除；key 不存在时返回 False。"""

    @abstractmethod
    async def count(self) -> int:
        """统计定时器数量。"""
