"""房间领域：房间状态（人数、房号、主客模式）与用户事件钩子命令值对象。

纯状态对象：不读写文件、不查找服务。默认主房间 ID 与「当前房号」都由构造方
注入，主客判断只做字符串比较。
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, Optional

from ushareiplay.modules.shared.errors import DomainError


class RoomError(DomainError):
    """房间规则失败。"""


class RoomAdminError(RoomError):
    """房管名单规则失败。"""


class AlreadyRoomAdmin(RoomAdminError):
    """屏幕显示目标已经是房管，邀请是多余动作。"""

    def __init__(self, user: str):
        super().__init__(user)
        self.user = user


class NotRoomAdmin(RoomAdminError):
    """屏幕显示目标还不是房管，解除是多余动作。"""

    def __init__(self, user: str):
        super().__init__(user)
        self.user = user


class RoomAdmins:
    """当前房间管理员名单（UI 可见昵称）。

    屏幕才是真相：这份集合是资料卡开关的抄写，供麦位观测与 `:info` 标注管理身份。
    只存可见昵称 —— 与 `_room_admin` 比对的下游（麦位、在线列表）拿到的都是 UI 名字。
    """

    def __init__(self):
        self._admins: set[str] = set()

    def add(self, username: str) -> None:
        if username:
            self._admins.add(username)

    def remove(self, username: str) -> None:
        self._admins.discard(username)

    def clear(self) -> None:
        self._admins.clear()

    def is_admin(self, username: str) -> bool:
        return bool(username) and username in self._admins

    def all(self) -> set[str]:
        return set(self._admins)


@dataclass(frozen=True)
class HookCommand:
    """一条用户事件钩子命令（持久化行在领域侧的投影）。"""

    id: int
    command: str
    owner: str


class RoomState:
    """房间静态/半静态状态：在线人数、专注人数、房间 ID、主/客房状态。"""

    def __init__(
        self,
        *,
        default_party_id: Optional[str] = None,
        current_party_id: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.default_party_id = default_party_id
        self._current_party_id = current_party_id or (lambda: None)
        self._user_count: Optional[int] = None
        self._focus_count: Optional[int] = None
        self._room_id: Optional[str] = None
        self._recommendation_enabled: Optional[bool] = None
        self._expected_party_id: Optional[str] = None
        self._is_guest_room: Optional[bool] = None

    @property
    def user_count(self) -> Optional[int]:
        return self._user_count

    @user_count.setter
    def user_count(self, value: int):
        self._user_count = value

    @property
    def focus_count(self) -> Optional[int]:
        return self._focus_count

    @focus_count.setter
    def focus_count(self, value: int):
        self._focus_count = value

    @property
    def room_id(self) -> Optional[str]:
        return self._room_id

    @room_id.setter
    def room_id(self, value: str):
        self._room_id = value

    @property
    def recommendation_enabled(self) -> Optional[bool]:
        return self._recommendation_enabled

    @recommendation_enabled.setter
    def recommendation_enabled(self, value: Optional[bool]):
        self._recommendation_enabled = value

    @property
    def expected_party_id(self) -> Optional[str]:
        return self._expected_party_id

    @expected_party_id.setter
    def expected_party_id(self, value: Optional[str]):
        self._expected_party_id = value

    @property
    def is_guest_room(self) -> bool:
        """是否处于他人房间（客房模式）。显式覆盖优先于房号比较。"""
        if self._is_guest_room is not None:
            return self._is_guest_room

        current_party_id = self.room_id or self._current_party_id()
        if current_party_id and self.default_party_id:
            return current_party_id.strip() != self.default_party_id.strip()
        return False

    @is_guest_room.setter
    def is_guest_room(self, value: Optional[bool]):
        self._is_guest_room = value

    @property
    def is_host_room(self) -> bool:
        return not self.is_guest_room

    def get_expected_party_id(self) -> Optional[str]:
        """当前应当所处的房间 ID（优先客房目标，回退配置的默认主房间）。"""
        if self.expected_party_id:
            return self.expected_party_id.strip()
        return self.default_party_id

    def adopt_host_room(self, room_id: Optional[str]) -> bool:
        """房间 ID 若就是配置中的主房间（群主转让）则恢复宿主模式。"""
        requested_id = (room_id or "").strip()
        configured_id = (self.default_party_id or "").strip()
        if not requested_id or requested_id != configured_id:
            return False
        self.promote_to_host_room(requested_id)
        return True

    def promote_to_host_room(self, room_id: Optional[str] = None) -> None:
        """把当前房间认作机器人自有房间并恢复宿主模式。"""
        self.expected_party_id = None
        if room_id:
            self.room_id = room_id
        self._is_guest_room = False

    def clear(self) -> None:
        """清空房间状态；跨模块的清理由调用方（use case）负责。"""
        self._user_count = None
        self._focus_count = None
        self._room_id = None
        self._recommendation_enabled = None
        self._is_guest_room = None


# --------------------------------------------------------------------------
# 房间名（ADR-0001）
# --------------------------------------------------------------------------

#: ADR-0001 的分隔符：全角竖线 U+FF5C。
FULLWIDTH_SEPARATOR = '｜'

#: 房间标题的展示长度上限
TITLE_MAX_LENGTH = 12
#: 房间话题的展示长度上限
TOPIC_MAX_LENGTH = 15

#: 截断点：半角/全角竖线、CJK 竖笔，以及半角/全角左括号
_BANNER_SEPARATORS = ('|', '｜', '丨', '(', '（')

#: 设置面板里「推荐分发」那一行显示的文案 -> 布尔状态。
RECOMMENDATION_OPEN_TEXT = '所有人'
RECOMMENDATION_CLOSED_TEXT = '关闭推荐分发'


class ProfileError(DomainError):
    """房间档案规则失败。"""


class InvalidRoomName(ProfileError):
    """房名 / 主题不合法；异常文本就是既有的公屏文案。"""


class ProfileCooldown(ProfileError):
    """字段预算或抽屉表面仍在冷却，此刻不能开始一次写入。"""

    def __init__(self, field: str, remaining_minutes: int):
        super().__init__(field, remaining_minutes)
        self.field = field
        self.remaining_minutes = remaining_minutes


def clean_banner_text(text: str, max_length: int) -> str:
    """把标题/话题文本截到第一个装饰符之前，去空白并限长。

    逐个分隔符依次截断（每个都在前一步的结果上继续切），与原先两份内联实现
    的切分顺序一致。
    """
    cleaned = text or ""
    for separator in _BANNER_SEPARATORS:
        cleaned = cleaned.split(separator)[0]
    return cleaned.strip()[:max_length]


def validate_theme(theme: str) -> str:
    """校验主题并返回 strip 后的值。

    既有的长度判定在 strip **之前**（`set_theme("  听歌  ")` 因原始长度 6 > 2
    被拒），这条怪癖逐字保留。
    """
    if len(theme) > 2:
        raise InvalidRoomName('主题最多两个字符')
    new_theme = theme.strip()
    if not new_theme:
        raise InvalidRoomName('主题不能为空')
    return new_theme


def compose_room_name(theme: str, title: Optional[str]) -> str:
    """合成房间名 `{theme}｜{title}`（ADR-0001 不变量）。"""
    return f"{theme}{FULLWIDTH_SEPARATOR}{title or ''}"


def parse_room_title_text(room_title_text: str):
    """从 UI 读到的房间名里拆出 `(主题, 标题)`；没有分隔符则 None。

    `split(sep, 1)` 只切第一个 —— 标题里若还有分隔符，它会连同后半段一起留在
    标题里（与既有实现逐字一致）。
    """
    if FULLWIDTH_SEPARATOR not in room_title_text:
        return None
    theme_part, title_part = room_title_text.split(FULLWIDTH_SEPARATOR, 1)
    return theme_part.strip(), title_part.strip()


def recommendation_status_from_text(text: str) -> Optional[bool]:
    """把设置面板里推荐状态那一行的文案翻译成布尔状态。"""
    if RECOMMENDATION_OPEN_TEXT in text:
        return True
    if RECOMMENDATION_CLOSED_TEXT in text:
        return False
    return None


# --------------------------------------------------------------------------
# 草稿冷却内核
# --------------------------------------------------------------------------


class PendingWrite:
    """一个待写入值的冷却与重试状态机。

    调用方的典型用法：写入没发生（跳过）就不记账；真的写过就推进时钟
    （成功、失败、异常都一样）；成功才清空待写入值。
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
        """推进冷却时钟：每次尝试都要调用一次，成功、失败、异常都一样。"""
        self.last_attempt_at = now or datetime.now()

    def clear(self) -> None:
        """写入成功：清空待写入值。"""
        self.pending = None


#: 房间话题冷却时长（分钟）
TOPIC_COOLDOWN_MINUTES = 5
#: 派对公告冷却时长（分钟）
NOTICE_COOLDOWN_MINUTES = 15
#: 房名（标题 + 主题）共享冷却时长（分钟）
TITLE_COOLDOWN_MINUTES = 10

#: 草稿库拥有的字段，顺序即默认冷却表里的顺序。
FIELDS = ('topic', 'notice', 'title')

#: 两次「开始一次抽屉写入」之间的最小间隔（秒）。
SURFACE_SPACING_SECONDS = 60


class ProfileDraftStore:
    """三个字段草稿的冷却与待写入状态。

    本类不碰 UI、不读配置、不认识 Soul 的任何 selector：它只回答「这个字段
    现在能不能写、要等几分钟、用户想写的是什么」。主题不单独占预算，它只是
    房名草稿的前缀（ADR-0001 的共享冷却）。
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
        self._pending_theme: Optional[str] = None

    def _write(self, field: str) -> PendingWrite:
        try:
            return self._writes[field]
        except KeyError:
            raise KeyError(
                f"unknown draft field {field!r}; expected one of {FIELDS}"
            ) from None

    def fields(self):
        return FIELDS

    def pending(self, field: str) -> Any:
        """该字段当前排队中的文案，没有则 None。"""
        return self._write(field).pending

    def set_pending(self, field: str, value: Any) -> None:
        """排队一条草稿；`None` 表示清空。"""
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

    def surface_last_touched(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """三个字段里最近一次真正动手写抽屉的时刻（没写过则 None）。"""
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
        """该字段自己的 5/15/10 分钟到了没（不含抽屉表面节奏）。"""
        return self._write(field).can_apply_now()

    def can_start_write(self, field: str, now: Optional[datetime] = None) -> bool:
        """现在能不能开始一次该字段的抽屉写入：字段预算 + 抽屉表面都安静。"""
        if not self._write(field).can_apply_now():
            return False
        return self.spacing_remaining_seconds(now) <= 0.0

    def require_can_start(self, field: str, now: Optional[datetime] = None) -> None:
        """同 `can_start_write`，但冷却中抛 `ProfileCooldown`（含剩余分钟数）。"""
        if self.can_start_write(field, now):
            return
        raise ProfileCooldown(field, self.minutes_until_write(field, now))

    def minutes_until_write(self, field: str, now: Optional[datetime] = None) -> int:
        """距离真的能写还差几分钟：字段预算与抽屉表面里更晚的那一个。

        字段预算那一半沿用 `PendingWrite.remaining_minutes()` 的 `int()` 向下截断；
        表面那一半向上取整，因为 0 会被读成「马上就能写」。
        """
        budget = self._write(field).remaining_minutes()
        spacing = self.spacing_remaining_seconds(now)
        return max(budget, math.ceil(spacing / 60) if spacing > 0 else 0)

    def remaining_minutes(self, field: str) -> int:
        """距离可写入还差多少分钟（未冷却时为 0）。"""
        return self._write(field).remaining_minutes()

    def mark_attempted(self, field: str, now: Optional[datetime] = None) -> None:
        """推进该字段的冷却时钟；「跳过」不算一次尝试，不要调用它。"""
        self._write(field).mark_attempted(now)

    def last_attempt_at(self, field: str) -> Optional[datetime]:
        """该字段上一次尝试的时刻（测试与诊断用）。"""
        return self._write(field).last_attempt_at

    def set_last_attempt_at(self, field: str, value: Optional[datetime]) -> None:
        self._write(field).last_attempt_at = value

    def cooldown_minutes(self, field: str) -> int:
        return self._write(field).cooldown_minutes

    def set_cooldown_minutes(self, field: str, minutes: int) -> None:
        self._write(field).cooldown_minutes = minutes

    def pending_theme(self) -> Optional[str]:
        return self._pending_theme

    def set_pending_theme(self, theme: Optional[str]) -> None:
        self._pending_theme = theme

    def parse_room_title(self, room_title_text: str):
        """从 UI 读到的房间名里拆出 `(主题, 标题)`；没有分隔符则 None。"""
        return parse_room_title_text(room_title_text)


# --------------------------------------------------------------------------
# 派对生命周期、送礼与福袋规则（#552）
# --------------------------------------------------------------------------

#: 礼物列表兜底礼物，固定为列表首位，点击即送无需点赠送。
YELLOW_DUCK_NAME = "小黄鸭"

MAX_REDEMPTIONS = 50
PACK_USAGE = '用法: :pack [list|open [level] [countdown]|redeem]'
OPEN_USAGE = '用法: :pack open [level] [countdown]（level 取 1~5，countdown 取 0/1/3/5/10）'

#: 阶段文案 → 福袋等级：「第一阶段奖励」即 1 级福袋。
_PHASE_PATTERN = re.compile(r'第([一二三四五])阶段')
_PHASE_LEVELS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}

#: 倒计时选项：0 表示即刻抢，其余是分钟数。
COUNTDOWN_OPTIONS = {0: '即刻抢', 1: '1分钟', 3: '3分钟', 5: '5分钟', 10: '10分钟'}

_HEAT_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*([万wW])?')
_ZERO_PACK_PATTERN = re.compile(r'(?<!\d)0\s*个')


class PartyLifecycleState:
    """派对生命周期状态：启动时间、自动重启触发时长与每日自动结束去重。"""

    def __init__(self, trigger_minutes: int = 720):
        self.init_time: Optional[datetime] = None
        self.last_auto_end_date: Optional[date] = None
        self.trigger_minutes: int = trigger_minutes

    def initialize(
        self,
        now: Optional[datetime] = None,
        trigger_minutes: Optional[int] = None,
    ) -> bool:
        """首次初始化派对计时；已初始化时保持原 init_time。"""
        if self.init_time is not None:
            return False
        self.init_time = now or datetime.now()
        if trigger_minutes is not None:
            self.trigger_minutes = trigger_minutes
        return True

    def reset_time(self, now: Optional[datetime] = None) -> datetime:
        """重置派对创建时间。"""
        self.init_time = now or datetime.now()
        return self.init_time

    def mark_auto_ended(self, today: date) -> None:
        """记录今日已尝试过自动结束（成功或失败均每天最多一次）。"""
        self.last_auto_end_date = today

    def should_auto_restart(
        self,
        now: datetime,
        *,
        user_count: int,
        is_guest_room: bool,
    ) -> bool:
        """是否满足自动重启派对条件：宿主房、已过触发分钟数、今日未触发且仅剩 1 人。"""
        if is_guest_room or self.init_time is None:
            return False
        if self.last_auto_end_date == now.date():
            return False
        minutes_since_init = (now - self.init_time).total_seconds() / 60
        if minutes_since_init < self.trigger_minutes:
            return False
        if user_count == -1:
            return False
        return user_count == 1

    def format_duration_info(self, now: Optional[datetime] = None) -> Optional[str]:
        """格式化派对开始时间与持续时长，未初始化返回 None。"""
        if self.init_time is None:
            return None
        current_time = now or datetime.now()
        duration = current_time - self.init_time
        total_minutes = int(duration.total_seconds() / 60)
        hours = total_minutes // 60
        minutes = total_minutes % 60
        start_time_str = self.init_time.strftime("%H:%M")
        duration_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
        return f"{start_time_str}, {duration_str}"


def party_create_mode(raw_mode: Optional[str]) -> str:
    """规范化建房模式：仅接受 new_party_entry / restore_party，其余回退 new_party_entry。"""
    if raw_mode in ('new_party_entry', 'restore_party'):
        return raw_mode
    return 'new_party_entry'


def is_zero_packs(text: Optional[str]) -> bool:
    """福袋标签文案是否为 0 个（如「礼物福袋  (0个)」）。"""
    return bool(_ZERO_PACK_PATTERN.search(text or ''))


def parse_heat(text: Optional[str]) -> Optional[int]:
    """提取热力数值，兼容 `万`/`w` 单位与千分位逗号。"""
    match = _HEAT_PATTERN.search((text or '').replace(',', ''))
    if not match:
        return None
    value = float(match.group(1))
    return int(value * 10000) if match.group(2) else int(value)


def parse_pack_level(text: Optional[str]) -> Optional[int]:
    """从「第X阶段奖励」里读出福袋等级；不是阶段文案返回 None。"""
    match = _PHASE_PATTERN.search(text or '')
    return _PHASE_LEVELS[match.group(1)] if match else None


def parse_countdown(text: Optional[str]) -> Optional[int]:
    """从「即刻抢 | 所有人」/「3分钟 | 所有人」里读出倒计时分钟数（即刻抢 = 0）。"""
    cleaned = (text or '').strip()
    if '即刻抢' in cleaned:
        return 0
    match = re.search(r'(\d+)\s*分钟', cleaned)
    return int(match.group(1)) if match else None


def format_packs(packs: list[tuple[int, str]]) -> str:
    """把扫描结果渲染成一行可读文案。"""
    counts: dict[int, int] = {}
    names: dict[int, str] = {}
    for level, name in packs:
        counts[level] = counts.get(level, 0) + 1
        names.setdefault(level, name)
    parts = []
    for level in sorted(counts, reverse=True):
        name = names[level]
        suffix = f'×{counts[level]}' if counts[level] > 1 else ''
        parts.append(f'{name}（{level}级）{suffix}' if name else f'{level}级福袋{suffix}')
    return f'福袋列表（共{len(packs)}个）：' + '、'.join(parts)


def parse_open_pack_args(
    parameters: list[str],
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """解析 :pack open 的参数：level（1~5，可省略）、countdown（0/1/3/5/10，默认即刻抢）。"""
    if len(parameters) > 2:
        return None, None, OPEN_USAGE
    level: Optional[int] = None
    countdown = 0
    if parameters:
        try:
            level = int(parameters[0])
        except (TypeError, ValueError):
            return None, None, OPEN_USAGE
        if not 1 <= level <= 5:
            return None, None, OPEN_USAGE
    if len(parameters) > 1:
        try:
            countdown = int(parameters[1])
        except (TypeError, ValueError):
            return None, None, OPEN_USAGE
        if countdown not in COUNTDOWN_OPTIONS:
            return None, None, OPEN_USAGE
    return level, countdown, None


def should_skip_auto_pack(user_count: Optional[int], item_text: str) -> bool:
    """人数不超过 10 人时，自动模式仅允许低/中级或一/二级福袋。"""
    if user_count is None or user_count > 10:
        return False
    return not (
        "初级" in item_text
        or "中级" in item_text
        or "一级" in item_text
        or "二级" in item_text
    )
