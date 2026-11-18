"""定时器领域对象：纯数据，不依赖 Tortoise。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Timer:
    key: str
    message: str
    target_time: str
    repeat: bool = False
    enabled: bool = True
    next_trigger: datetime | None = None
