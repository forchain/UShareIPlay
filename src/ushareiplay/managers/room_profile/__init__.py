"""房间档案深度模块的契约层：抽屉 UI 驱动端口与字段草稿库。

命令层只需要知道两件事：把要写的话交给 `RoomProfileManager` 的某个 `set_*`，
以及在需要直接动抽屉时用 `with_window_open()`。Appium 细节、冷却算术与
`{theme}｜{title}` 的合成规则都在这个子包内部。
"""

from ushareiplay.modules.room.domain import (
    NOTICE_COOLDOWN_MINUTES,
    TITLE_COOLDOWN_MINUTES,
    TOPIC_COOLDOWN_MINUTES,
    ProfileDraftStore,
)
from ushareiplay.modules.room.ports import (
    DEFAULT_ENTRY_KEYS,
    DIALOG_KEYS,
    DRAWER_KEY,
    RoomProfileDrawerDriverPort,
)
from ushareiplay.managers.room_profile.manager import RoomProfileManager
from ushareiplay.modules.room.ports import PartySettingsDriverPort
from ushareiplay.adapters.outbound.appium.soul.room_profile import (
    SoulDrawerDriver,
    SoulPartySettingsDriver,
)

__all__ = [
    "DEFAULT_ENTRY_KEYS",
    "DIALOG_KEYS",
    "DRAWER_KEY",
    "NOTICE_COOLDOWN_MINUTES",
    "PartySettingsDriverPort",
    "ProfileDraftStore",
    "RoomProfileDrawerDriverPort",
    "RoomProfileManager",
    "SoulDrawerDriver",
    "SoulPartySettingsDriver",
    "TITLE_COOLDOWN_MINUTES",
    "TOPIC_COOLDOWN_MINUTES",
]
