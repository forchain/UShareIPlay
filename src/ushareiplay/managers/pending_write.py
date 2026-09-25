"""冷却时钟 + 待写入值 + 失败重试：一个参数化内核。

三个 manager（房间名 / 派对公告 / 房间话题）原先各写一份同样的状态机：

    一个冷却时钟（last_attempt_at） -> can_apply_now() / 剩余分钟数
    一个待写入值（next_title / pending_notice / next_topic）
    每次尝试都推进时钟（成功、失败、异常都一样）；失败则保留待写入值，
    等下个冷却周期再试

三份实现的冷却时长不同（10 / 15 / 5 分钟）——那是参数；但计时算术也各写各的，
话题那份还把算术内联在 `get_status()` 与 `change_topic()` 里，于是「什么时候推进
时钟」这件事在三个文件里各有一个版本。

本类只提供计时机制，不碰 UI、不读配置、不碰房间状态：manager 仍然是面向调用方
的接缝，只有计时机制下沉到这里。按 ADR-0001 的逻辑执行（它自己诊断出「冷却 /
pending 编排重复」），但框架为 manager 持有的私有内核，而不是对 Room Name
不变量的重新拆分。
"""

from datetime import datetime
from typing import Any, Optional


class PendingWrite:
    """一个待写入值的冷却与重试状态机。

    调用方的典型用法（见 RoomNameManager.process_pending_update）：

        if not write.can_apply_now():
            return {'cooldown': True, 'remaining_minutes': write.remaining_minutes()}
        result = self._write_ui(write.pending)
        write.mark_attempted()          # 无论成败都要推进时钟
        if 'error' not in result:
            write.clear()               # 成功才清空待写入值
    """

    def __init__(self, cooldown_minutes: int, label: str = ""):
        self.cooldown_minutes = cooldown_minutes
        self.label = label
        self.pending: Optional[Any] = None
        self.last_attempt_at: Optional[datetime] = None

    @property
    def has_pending(self) -> bool:
        return self.pending is not None

    def submit(self, value: Any) -> None:
        """记录待写入值。不做冷却判断 —— 那是 `can_apply_now()` 的事。"""
        self.pending = value

    def can_apply_now(self) -> bool:
        """从未尝试过、或已过冷却时长时为 True。"""
        if self.last_attempt_at is None:
            return True
        elapsed = (datetime.now() - self.last_attempt_at).total_seconds()
        return elapsed >= self.cooldown_minutes * 60

    def remaining_minutes(self) -> int:
        """距离可写入还差多少分钟（未冷却时为 0）。"""
        if self.last_attempt_at is None:
            return 0
        remaining_seconds = self.cooldown_minutes * 60 - (
            datetime.now() - self.last_attempt_at
        ).total_seconds()
        return max(0, int(remaining_seconds / 60))

    def mark_attempted(self, now: Optional[datetime] = None) -> None:
        """推进冷却时钟：每次尝试都要调用一次，成功、失败、异常都一样。

        一个冷却周期内不得对同一个待写入值发起第二次尝试，否则会被 update()
        循环变成紧循环重试 —— 因此时钟必须在对它再次发起尝试**之前**推进。
        在这一点上，调用点有两种合法顺序（都是既有的、有意的，别顺手统一）：

        - UI 调用自己把异常收敛成 `{'error': ...}` 时：调用**之后**推进
          （房间名、公告），读起来就是「无论成败都要推进」。
        - UI 调用可能抛出时：**先**推进再调用（话题）—— 抛出也算一次尝试，
          不能因为异常就跳过整个冷却周期。
        """
        self.last_attempt_at = now or datetime.now()

    def clear(self) -> None:
        """写入成功：清空待写入值。"""
        self.pending = None
