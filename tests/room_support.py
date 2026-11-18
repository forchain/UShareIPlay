"""房间切片测试台：按组合根的方式构造并接线房间状态、在线集合与钩子引擎。"""

from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.modules.command.domain import CommandCatalogue
from ushareiplay.modules.room.use_cases import (
    PresenceTracker,
    RoomStateService,
    UserEventHooks,
)


def configured_room_state(**kwargs) -> RoomStateService:
    """带真实命令目录的房间状态（旧 `RoomState.initialize(catalogue=...)` 的对应物）。"""
    if kwargs.get("catalogue") is None:
        kwargs["catalogue"] = CommandCatalogue.from_config(ConfigLoader.load_config())
    kwargs.setdefault("logger", None)
    return RoomStateService(**kwargs)


def wire_room_state(room_state: RoomStateService) -> None:
    """把同一份房间状态塞进已经构造好的旧单例（组合根在启动时做的事）。"""
    from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.playback_muting import PlaybackMuting
    from tests.room_profile_support import RoomProfileManager
    from ushareiplay.managers.seat_manager import SeatManager
    from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager

    for cls, attr in (
        (CommandManager, "room_state"),
        (PartyManager, "_room_state"),
        (RoomProfileManager, "_room_state"),
        (InfoManager, "_room_state"),
        (PlaybackMuting, "room_state"),
        (SeatManager, "_room_state"),
        (SeatObservationManager, "room_state"),
    ):
        if cls.is_initialized():
            setattr(cls.instance(), attr, room_state)


def make_hooks(
    *,
    users=None,
    presence=None,
    memory=None,
    logger=None,
    repository=None,
) -> UserEventHooks:
    """按组合根的方式构造钩子引擎（Tortoise 仓储 + 队列出口）。"""
    from ushareiplay.adapters.inbound.runtime.hook_command_sink import QueueHookCommandSink
    from ushareiplay.adapters.outbound.persistence.user_event_hook_repository import (
        TortoiseUserEventHookRepository,
    )
    from ushareiplay.adapters.outbound.persistence.user_repository import (
        TortoiseUserRepository,
    )

    users = users or TortoiseUserRepository()
    return UserEventHooks(
        repository=repository or TortoiseUserEventHookRepository(users=users),
        users=users,
        sink=QueueHookCommandSink(MessageQueue.instance()),
        presence=presence or PresenceTracker(),
        memory=memory,
        logger=logger,
    )
