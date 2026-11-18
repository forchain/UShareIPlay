"""跨切端口：公屏消息、时钟、UI 独占会话。

端口由共享内核定义，生产实现在适配器/现有组合根对象上，测试替身在
`tests/fakes/`。端口只描述业务需要的能力，不泄漏 Appium / WebElement。
"""

from abc import ABC, abstractmethod
from datetime import datetime


class RoomMessenger(ABC):
    """向房间公屏发消息；`silent` 与静音命令必须照旧被遵守。"""

    @abstractmethod
    def send_screen_message(self, message: str, silent: bool = False):
        """发送一条公屏消息（静音时抑制并返回 None）。"""


class Clock(ABC):
    """可注入的时间源：当前时间与异步等待。"""

    @abstractmethod
    def now(self) -> datetime:
        """当前本地时间。"""

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """异步等待给定秒数。"""


class UISession(ABC):
    """独占 UI 执行权的会话租赁（可重入、可跳过、可被暂停闸门取消）。"""

    @property
    @abstractmethod
    def holds_session(self) -> bool:
        """当前 task 是否持有本租赁。"""

    @property
    @abstractmethod
    def busy_elsewhere(self) -> bool:
        """锁被并非当前 task 的其他流程持有。"""

    @abstractmethod
    def acquire(self, reason: str = "", *, skip_if_busy: bool = False):
        """异步上下文管理器；`skip_if_busy` 且他人占屏时 yield False。"""
