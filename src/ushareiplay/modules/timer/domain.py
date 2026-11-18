"""定时器领域：计划数据与纯时间规则，不依赖 ORM 或系统时钟。"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ushareiplay.modules.shared.errors import DomainError

_HH_MM = "%H:%M"
_HH_MM_SS = "%H:%M:%S"
_CLOCK_FORMAT_ERROR = "时间格式错误：支持 HH:MM / HH:MM:SS，或纯数字 N 表示延迟 N 秒"


class TimerError(DomainError):
    """定时器业务规则的显式失败。"""


class InvalidTimerSpec(TimerError):
    """时间/延迟参数不合法。"""


class TimerKeyConflict(TimerError):
    """业务 key 已存在。"""

    def __init__(self, key: str):
        super().__init__(f'ID "{key}" 已存在')


@dataclass(frozen=True)
class Timer:
    key: str
    message: str
    target_time: str
    repeat: bool = False
    enabled: bool = True
    next_trigger: datetime | None = None


def is_time_token(token: str) -> bool:
    """token 是否是时间字面量（延迟秒数或 HH:MM / HH:MM:SS）。"""
    t = (token or "").strip()
    if not t:
        return False
    if t.isdigit():
        return True
    parts = t.split(":")
    if len(parts) not in (2, 3):
        return False
    if not all(p.isdigit() for p in parts):
        return False
    if len(parts[0]) not in (1, 2):
        return False
    if any(len(p) != 2 for p in parts[1:]):
        return False
    return True


def compute_next_trigger(target_time: str, repeat: bool, now: datetime) -> datetime:
    """把用户输入的时间文法转成下一次触发时间。

    - 纯数字：延迟 N 秒执行一次（repeat 必须为 False）
    - HH:MM / HH:MM:SS：当天/次日的固定时间触发（repeat 可为 True）
    """
    raw = (target_time or "").strip()
    if raw.isdigit():
        seconds = int(raw)
        if seconds <= 0:
            raise InvalidTimerSpec("延迟秒数必须为正整数")
        # 防止误输入造成超长延迟；需要更长可改为显式时间点
        if seconds > 86400 * 30:
            raise InvalidTimerSpec("延迟秒数过大（最大支持 30 天内的延迟）")
        if repeat:
            raise InvalidTimerSpec("延迟模式不支持 repeat")
        return now + timedelta(seconds=seconds)

    fmt = _HH_MM_SS if raw.count(":") == 2 else _HH_MM
    try:
        target = datetime.strptime(raw, fmt).time()
    except ValueError:
        raise InvalidTimerSpec(_CLOCK_FORMAT_ERROR) from None
    candidate = datetime.combine(now.date(), target)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def next_daily_trigger(target_time: str, now: datetime) -> datetime:
    """当天/次日的 HH:MM 触发时间。

    旧恢复/加载逻辑只认 HH:MM，因此 HH:MM:SS 的重复任务不会被重排；
    这里保留该行为，`ValueError` 由调用方按原样忽略。
    """
    target = datetime.strptime((target_time or "").strip(), _HH_MM).time()
    candidate = datetime.combine(now.date(), target)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def advance_repeat(next_trigger: datetime, now: datetime) -> datetime:
    """重复任务触发后推进到未来：跳过停机期间错过的每一天。"""
    while next_trigger <= now:
        next_trigger += timedelta(days=1)
    return next_trigger


def reschedule_expired_repeat(timer: Timer, now: datetime) -> datetime | None:
    """暂停/加载时把已经过期的重复任务重排到未来；不需要重排返回 None。"""
    if not timer.repeat or not timer.target_time or timer.next_trigger is None:
        return None
    if timer.next_trigger > now:
        return None
    return next_daily_trigger(timer.target_time, now)
