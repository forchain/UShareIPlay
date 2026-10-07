"""房间档案深度模块的契约层：抽屉 UI 驱动端口与字段草稿库。

命令层只需要知道两件事：把要写的话交给 `RoomProfileManager` 的某个 `set_*`，
以及在需要直接动抽屉时用 `with_window_open()`。Appium 细节、冷却算术与
`{theme}｜{title}` 的合成规则都在这个子包内部。
"""

from ushareiplay.managers.room_profile.drafts import (
    NOTICE_COOLDOWN_MINUTES,
    TITLE_COOLDOWN_MINUTES,
    TOPIC_COOLDOWN_MINUTES,
    ProfileDraftStore,
)
from ushareiplay.managers.room_profile.driver import (
    DEFAULT_ENTRY_KEYS,
    DIALOG_KEYS,
    DRAWER_KEY,
    RoomProfileDrawerDriverPort,
)
from ushareiplay.managers.room_profile.manager import RoomProfileManager
from ushareiplay.managers.room_profile.soul_drawer import SoulDrawerDriver

__all__ = [
    "DEFAULT_ENTRY_KEYS",
    "DIALOG_KEYS",
    "DRAWER_KEY",
    "NOTICE_COOLDOWN_MINUTES",
    "ProfileDraftStore",
    "RoomProfileDrawerDriverPort",
    "RoomProfileManager",
    "SoulDrawerDriver",
    "TITLE_COOLDOWN_MINUTES",
    "TOPIC_COOLDOWN_MINUTES",
]
