"""座位面板的旧句柄 —— 实现已并入 `SeatSubsystem`（票 #400）。

面板展开/收起/滚动的实现在 #395 之后只存在于 `SeatPanelDriver` 里；本模块原本
留着一份近重复的副本，这次一并退役。`SeatUIManager` 保留下来只是为了让
`SeatObservationManager` 这类既有调用方继续可用（#402 删除）。
"""

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager.subsystem import SubsystemHandle


class SeatUIManager(SubsystemHandle, Singleton):
    """座位面板的向后兼容句柄（#400 合并，#402 删除）。"""

    def __init__(self, handler=None):
        super().__init__(handler)

    # 面板只有一份状态：旧类里那个独立缓存已经没有了，读写都落到驱动上。
    @property
    def is_expanded(self) -> bool:
        return bool(getattr(self.subsystem.panel, "is_expanded", False))

    def check_seats_state(self) -> bool:
        return self.subsystem.check_seats_state()

    async def expand_seats(self) -> bool:
        return await self.subsystem.expand_seats()

    async def collapse_seats(self) -> bool:
        return await self.subsystem.collapse_seats()

    async def expand_and_find_desks(self):
        return await self.subsystem.expand_and_find_desks()

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100) -> bool:
        return self.subsystem.scroll_to_row(desk_index, seat_desks, duration=duration)