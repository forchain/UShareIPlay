"""用户命名域：canonical 用户、别名链、等级与热力规则。

两个命名域在这里只以值对象区分（`CanonicalName`）；Soul UI 的可见昵称由
`use_cases.resolve_visible_username` 负责解析，领域层不做字符串猜测。
"""

from dataclasses import dataclass
from typing import Callable, Optional

from ushareiplay.modules.shared.errors import DomainError
from ushareiplay.modules.shared.names import CanonicalName

MAX_LEVEL = 9
OWNER_GIFT_MIN_LEVEL = 4


class UserError(DomainError):
    """用户规则失败。"""


class AliasCycleError(UserError):
    """别名链成环（含自引用），继续解析只会回到起点。"""


class InvalidLevelError(UserError):
    """等级超出 0-9。"""


class MissingCallerError(UserError):
    """非特权调用者连身份都无法验证。"""


class TargetNotBelowCallerError(UserError):
    """普通用户只能修改等级严格低于自己的目标。"""

    def __init__(self, target_level: int, caller_level: int):
        super().__init__(target_level, caller_level)
        self.target_level = target_level
        self.caller_level = caller_level


class NewLevelNotBelowCallerError(UserError):
    """普通用户设置的新等级必须严格低于自己。"""

    def __init__(self, new_level: int, caller_level: int):
        super().__init__(new_level, caller_level)
        self.new_level = new_level
        self.caller_level = caller_level


@dataclass(frozen=True)
class User:
    id: int
    username: CanonicalName
    level: int = 0
    heat_value: int = 0
    canonical_user_id: Optional[int] = None

    def __post_init__(self):
        if not isinstance(self.username, CanonicalName):
            object.__setattr__(self, "username", CanonicalName(self.username))

    @property
    def is_alias(self) -> bool:
        return self.canonical_user_id is not None


def follow_aliases(
    start: User, fetch: Callable[[int], Optional[User]]
) -> User:
    """沿 `canonical_user_id` 找到主账号。

    与旧 `UserDAO.resolve_canonical` 一致：目标记录缺失（断链）时回退到起点。
    环则抛 `AliasCycleError`；调用方若要保持旧行为（回退到起点）自行捕获。
    """
    current = start
    seen: set[int] = set()
    while current.canonical_user_id is not None:
        if current.id in seen:
            raise AliasCycleError(current.username.value)
        seen.add(current.id)
        target = fetch(current.canonical_user_id)
        if target is None:
            return start
        current = target
    return current


def validate_level(level: int) -> int:
    if not 0 <= level <= MAX_LEVEL:
        raise InvalidLevelError(level)
    return level


def heat_target_level(heat_value: int) -> int:
    """累计热力对应的等级门槛（与 MessageManager 既有阈值一致）。"""
    if heat_value > 1_000_000:
        return 8
    if heat_value > 100_000:
        return 7
    if heat_value > 10_000:
        return 6
    return 5
