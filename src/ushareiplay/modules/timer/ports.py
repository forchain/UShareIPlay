"""定时器持久化端口；语义与既有 TimerDAO 对齐。"""

from abc import ABC, abstractmethod
from datetime import datetime

from ushareiplay.modules.timer.domain import Timer


class TimerRepository(ABC):
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
