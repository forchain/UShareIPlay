"""共享内核：命名域值对象、角色与等级、领域异常、纯配置视图与跨切端口。"""

from ushareiplay.modules.shared.config import (
    ConfigError,
    ConfigSectionView,
    ConfigView,
    MissingConfigKey,
    MissingConfigSection,
    MissingElementKey,
    REQUIRED_ELEMENTS,
)
from ushareiplay.modules.shared.errors import DomainError
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.shared.names import CanonicalName, VisibleName
from ushareiplay.modules.shared.ports import Clock, RoomMessenger, UISession
from ushareiplay.modules.shared.roles import (
    DEFAULT_ADMIN_USERS,
    DEFAULT_COMMAND_LEVEL,
    DEFAULT_ROOM_OWNER,
    DEFAULT_SYSTEM_USERS,
    RolePolicy,
    min_command_level,
    resolve_command_level,
)

__all__ = [
    "CanonicalName",
    "Clock",
    "ConfigError",
    "ConfigSectionView",
    "ConfigView",
    "DEFAULT_ADMIN_USERS",
    "DEFAULT_COMMAND_LEVEL",
    "DEFAULT_ROOM_OWNER",
    "DEFAULT_SYSTEM_USERS",
    "DomainError",
    "MessageInfo",
    "MissingConfigKey",
    "MissingConfigSection",
    "MissingElementKey",
    "REQUIRED_ELEMENTS",
    "RolePolicy",
    "RoomMessenger",
    "UISession",
    "VisibleName",
    "min_command_level",
    "resolve_command_level",
]
