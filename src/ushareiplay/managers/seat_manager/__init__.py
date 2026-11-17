from ushareiplay.managers.seat_manager.base import SeatManagerBase
from ushareiplay.managers.seat_manager.subsystem import SeatSubsystem
from ushareiplay.managers.seat_manager.seat_panel_reader import (
    Reading,
    SeatPanelReader,
)
from ushareiplay.managers.seat_manager.seat_ledger import (
    SeatObservationGateState,
    SeatRescanCooldownPolicy,
)
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
)

__all__ = [
    "SeatManager",
    "SeatManagerBase",
    "SeatSubsystem",
    "Reading",
    "SeatPanelReader",
    "SeatObservationGateState",
    "SeatObservationManager",
    "SeatRescanCooldownPolicy",
]


class SeatManager(SeatSubsystem, SeatManagerBase):
    """座位管理的唯一实现与受保护单例绑定。

    真实逻辑、`@guest_room_guard` 与 UI 会话锁都在 `SeatSubsystem` 上；本类只负责
    单例契约（`initialize` / `instance`）与组合根注入。`subsystem` 是既有接线使用
    的只读别名，指向同一实例。
    """

    @property
    def subsystem(self) -> "SeatManager":
        return self
