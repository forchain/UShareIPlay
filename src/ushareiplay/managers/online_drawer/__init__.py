"""在线用户抽屉深度模块的契约层：抽屉 UI 驱动端口与唯一的会话所有者。

调用方只需要知道两件事：用 `OnlineDrawerManager.instance().drawer_session(...)`
在抽屉开着的情况下做事，以及在任何按名字找人的动作之前调用
`resolve_visible_username(...)` 把 DB 的 canonical 名换成 UI 上可见的昵称。

Appium 手势、元素 key、坐标与落定时间都在这个子包内部；旧实现在各自的后续 ticket
里迁移过来之前保持原样可用（在线名单抓取已于 #432 迁入，`UserManager` / 送礼 / 房管
等仍待各自 ticket）。
"""

from ushareiplay.managers.online_drawer.driver import (
    CLOSE_KEYS,
    DEFAULT_SCROLL_DURATION_MS,
    ENTRY_KEY,
    ONLINE_CONTAINER_KEY,
    ROW_CONTAINER_KEY,
    ROW_FOLLOW_STATE_KEY,
    ROW_NAME_KEY,
    MemberRow,
    OnlineDrawerDriverPort,
)
from ushareiplay.managers.online_drawer.manager import OnlineDrawerManager
from ushareiplay.managers.online_drawer.soul_driver import SoulOnlineDrawerDriver

__all__ = [
    "CLOSE_KEYS",
    "DEFAULT_SCROLL_DURATION_MS",
    "ENTRY_KEY",
    "ONLINE_CONTAINER_KEY",
    "ROW_CONTAINER_KEY",
    "ROW_FOLLOW_STATE_KEY",
    "ROW_NAME_KEY",
    "MemberRow",
    "OnlineDrawerDriverPort",
    "OnlineDrawerManager",
    "SoulOnlineDrawerDriver",
]
