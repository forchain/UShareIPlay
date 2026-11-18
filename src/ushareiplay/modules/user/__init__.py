"""用户业务包：canonical 命名域、别名、等级与热力。"""

from ushareiplay.modules.user.domain import (
    MAX_LEVEL,
    OWNER_GIFT_MIN_LEVEL,
    AliasCycleError,
    ChatLogEntry,
    InvalidLevelError,
    MemorySettings,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
    User,
    UserError,
    UserMemory,
    follow_aliases,
    heat_target_level,
    validate_level,
)
from ushareiplay.modules.user.ports import (
    ChatLogRepository,
    MemoryDistiller,
    UserMemoryRepository,
    UserRepository,
)
from ushareiplay.modules.user.use_cases import (
    BindAlias,
    GetLevel,
    ResolveVisibleUsername,
    SetLevel,
    UserMemoryService,
)

__all__ = [
    "AliasCycleError",
    "BindAlias",
    "ChatLogEntry",
    "ChatLogRepository",
    "GetLevel",
    "InvalidLevelError",
    "MAX_LEVEL",
    "MemoryDistiller",
    "MemorySettings",
    "MissingCallerError",
    "NewLevelNotBelowCallerError",
    "OWNER_GIFT_MIN_LEVEL",
    "ResolveVisibleUsername",
    "SetLevel",
    "TargetNotBelowCallerError",
    "User",
    "UserError",
    "UserMemory",
    "UserMemoryRepository",
    "UserMemoryService",
    "UserRepository",
    "follow_aliases",
    "heat_target_level",
    "validate_level",
]
