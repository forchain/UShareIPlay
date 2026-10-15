"""房间档案的草稿库：三个字段的冷却时钟与待写入文案。

原先话题、公告、房名各持一份 `PendingWrite`（冷却 5 / 15 / 10 分钟），冷却
算术虽然已经下沉到同一个内核，但「哪个字段剩几分钟、谁先写、谁排队」这个状态
仍然散在三个 manager 上。本模块把它们收成一处：一个字段一个 `PendingWrite`，
互不消耗预算；主题不占独立预算，它跟着房名走（ADR-0001 的共享冷却）。

冷却算术一律委托给 `PendingWrite`，因此 `remaining_minutes()` 的 `int()`
向下截断（刚推进时钟就报 9 分钟）与三份旧实现逐字一致 —— ADR-0009 的行为
等价性要求不允许在这里「顺手修正」。

推荐分发不在本模块：它没有冷却，是一次性的开关，#393 处理。
"""

import math
from datetime import datetime
from typing import Any, Dict, Optional

from ushareiplay.managers.pending_write import PendingWrite

#: 房间话题冷却时长（分钟）
TOPIC_COOLDOWN_MINUTES = 5
#: 派对公告冷却时长（分钟）
NOTICE_COOLDOWN_MINUTES = 15
#: 房名（标题 + 主题）共享冷却时长（分钟）
TITLE_COOLDOWN_MINUTES = 10

#: 草稿库拥有的字段，顺序即默认冷却表里的顺序。
FIELDS = ('topic', 'notice', 'title')

#: 两次「开始一次抽屉写入」之间的最小间隔（秒）。
#:
#: 三个字段各有各的预算（5 / 15 / 10 分钟），但 Soul 限制的是**房间信息面板的
#: 编辑动作**本身：话题刚落地 6 秒再去改房名，提交就被判「改得太频繁」。被拒一次
#: 的代价是一整个字段周期（房名 = 10 分钟静默），所以宁可在这里多等 60 秒 ——
#: 相对字段预算是零头，却能把「承诺 soon -> 被拒 -> 罚 10 分钟」换成「下一拍写成功」。
SURFACE_SPACING_SECONDS = 60


class ProfileDraftStore:
    """三个字段草稿的冷却与待写入状态。

    本类不碰 UI、不读配置、不认识 Soul 的任何 selector：它只回答「这个字段
    现在能不能写、要等几分钟、用户想写的是什么」。

    Args:
        topic_cooldown_minutes: 话题冷却，缺省 5。
        notice_cooldown_minutes: 公告冷却，缺省 15。
        title_cooldown_minutes: 房名共享冷却，缺省 10。
    """

    def __init__(
        self,
        topic_cooldown_minutes: int = TOPIC_COOLDOWN_MINUTES,
        notice_cooldown_minutes: int = NOTICE_COOLDOWN_MINUTES,
        title_cooldown_minutes: int = TITLE_COOLDOWN_MINUTES,
    ):
        self._writes: Dict[str, PendingWrite] = {
            'topic': PendingWrite(cooldown_minutes=topic_cooldown_minutes, label='topic'),
            'notice': PendingWrite(cooldown_minutes=notice_cooldown_minutes, label='notice'),
            'title': PendingWrite(cooldown_minutes=title_cooldown_minutes, label='title'),
        }
        # 主题不单独占预算：它只是房名草稿的前缀（ADR-0001 的 {theme}｜{title}）。
        self._pending_theme: Optional[str] = None

    # ------------------------------------------------------------------
    # 字段访问
    # ------------------------------------------------------------------

    def _write(self, field: str) -> PendingWrite:
        try:
            return self._writes[field]
        except KeyError:
            raise KeyError(
                f"unknown draft field {field!r}; expected one of {FIELDS}"
            ) from None

    def fields(self):
        return FIELDS

    # ------------------------------------------------------------------
    # 草稿
    # ------------------------------------------------------------------

    def pending(self, field: str) -> Any:
        """该字段当前排队中的文案，没有则 None。"""
        return self._write(field).pending

    def set_pending(self, field: str, value: Any) -> None:
        """排队一条草稿；`None` 表示清空。

        这是**唯一**的排队入口：原先还有一个纯转发的 `submit()`，两条同义路径
        只会让人猜哪条才是被推荐的那条。
        """
        write = self._write(field)
        if value is None:
            write.clear()
        else:
            write.submit(value)

    def has_pending(self, field: str) -> bool:
        return self._write(field).has_pending

    def clear(self, field: str) -> None:
        """写入成功：清空待写入值。"""
        self._write(field).clear()

    # ------------------------------------------------------------------
    # 冷却：两个问题分开答
    # ------------------------------------------------------------------

    def surface_last_touched(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """三个字段里**最近**一次真正动手写抽屉的时刻（没写过则 None）。"""
        stamps = [w.last_attempt_at for w in self._writes.values() if w.last_attempt_at]
        return max(stamps) if stamps else None

    def spacing_remaining_seconds(self, now: Optional[datetime] = None) -> float:
        """距离抽屉表面安静下来还差多少秒 —— 表面是一块，不分字段。"""
        last = self.surface_last_touched(now)
        if last is None:
            return 0.0
        reference = now or datetime.now()
        elapsed = (reference - last).total_seconds()
        return max(0.0, SURFACE_SPACING_SECONDS - elapsed)

    def can_apply_now(self, field: str) -> bool:
        """该字段**自己的**预算够不够：从未尝试过、或已过冷却时长时为 True。

        这只回答「字段自己的 5/15/10 分钟到了没」。抽屉**会话内部**的连带动作
        （房名写入顺手把被冲掉的公告当场补回去，用户故事 #6）问的是这个问题 ——
        它不开新的写入会话，因此不该被表面节奏闸拦去排队。
        要「开始一次新的抽屉写入」，请问 `can_start_write()`。
        """
        return self._write(field).can_apply_now()

    def can_start_write(self, field: str, now: Optional[datetime] = None) -> bool:
        """现在能不能**开始**一次该字段的抽屉写入：字段预算 + 抽屉表面都安静。"""
        if not self._write(field).can_apply_now():
            return False
        return self.spacing_remaining_seconds(now) <= 0.0

    def minutes_until_write(self, field: str, now: Optional[datetime] = None) -> int:
        """距离真的能写还差几分钟：字段预算与抽屉表面里更晚的那一个。

        字段预算那一半沿用 `PendingWrite.remaining_minutes()` 的 `int()` 向下截断
        （ADR-0009 要求逐字一致）；表面那一半向上取整，因为 0 会被读成「马上就能写」，
        而那正是被拒一次的起点。
        """
        budget = self._write(field).remaining_minutes()
        spacing = self.spacing_remaining_seconds(now)
        return max(budget, math.ceil(spacing / 60) if spacing > 0 else 0)

    def remaining_minutes(self, field: str) -> int:
        """距离可写入还差多少分钟（未冷却时为 0）。"""
        return self._write(field).remaining_minutes()

    def mark_attempted(self, field: str, now: Optional[datetime] = None) -> None:
        """推进该字段的冷却时钟：每次尝试都要调用一次，成功、失败、异常都一样。"""
        self._write(field).mark_attempted(now)

    def last_attempt_at(self, field: str) -> Optional[datetime]:
        """该字段上一次尝试的时刻（测试与诊断用；生产写回请走 `mark_attempted`）。"""
        return self._write(field).last_attempt_at

    def set_last_attempt_at(self, field: str, value: Optional[datetime]) -> None:
        self._write(field).last_attempt_at = value

    def cooldown_minutes(self, field: str) -> int:
        return self._write(field).cooldown_minutes

    def set_cooldown_minutes(self, field: str, minutes: int) -> None:
        self._write(field).cooldown_minutes = minutes

    # ------------------------------------------------------------------
    # 主题（跟着房名走的草稿，不单独占冷却）
    # ------------------------------------------------------------------

    def pending_theme(self) -> Optional[str]:
        return self._pending_theme

    def set_pending_theme(self, theme: Optional[str]) -> None:
        self._pending_theme = theme

    # 房名合成**不在本模块**：`{theme}｜{title}` 有一个「排队主题为空时用当前
    # 主题兜底」的判定，那需要 manager 持有的 `current_theme`，本模块看不见。
    # 这里曾经有一份忽略该判定的副本，会拼出 `None｜标题`；零调用点，且迟早有人
    # 调用错的那一份，因此已删除。唯一一份在 `RoomProfileManager.compose_room_title`。

    def parse_room_title(self, room_title_text: str):
        """从 UI 读到的房间名里拆出 `(主题, 标题)`；没有分隔符则 None。

        分隔符是全角 `｜`（U+FF5C），`split(sep, 1)` 只切第一个 —— 与既有
        实现逐字一致（`initialize_from_ui` 与 `_parse_title_from_ui` 都如此），
        因此标题里若还有分隔符，它会连同后半段一起留在标题里。
        """
        if '｜' not in room_title_text:
            return None
        parts = room_title_text.split('｜', 1)
        if len(parts) != 2:
            return None
        return parts[0].strip(), parts[1].strip()
