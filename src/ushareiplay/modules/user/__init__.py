"""用户业务包：canonical 命名域、别名、等级与热力。"""

from ushareiplay.modules.user.domain import (
    MAX_LEVEL,
    OWNER_GIFT_MIN_LEVEL,
    AliasCycleError,
    InvalidLevelError,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
    User,
    UserError,
    follow_aliases,
    heat_target_level,
    validate_level,
)
from ushareiplay.modules.user.ports import UserRepository
from ushareiplay.modules.user.use_cases import (
    BindAlias,
    GetLevel,
    ResolveVisibleUsername,
    SetLevel,
)

__all__ = [
    "AliasCycleError",
    "BindAlias",
    "GetLevel",
    "InvalidLevelError",
    "MAX_LEVEL",
    "MissingCallerError",
    "NewLevelNotBelowCallerError",
    "OWNER_GIFT_MIN_LEVEL",
    "ResolveVisibleUsername",
    "SetLevel",
    "TargetNotBelowCallerError",
    "User",
    "UserError",
    "UserRepository",
    "follow_aliases",
    "heat_target_level",
    "validate_level",
]
