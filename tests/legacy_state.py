"""测试台：旧 `RoomState` / `PresenceTracker` / `OnlineListScraper` 单例名的替身。

生产代码已改成组合根注入；大量既有行为测试仍按旧单例名的 API 驱动状态
（`initialize()` / `instance()` / `reset_instance()`）。这里把这三个名字映射到
每个测试共享的一份注入式对象上，并保持对象身份不变 —— 测试里重置的是同一份
状态，构造较早的组件看到的也是同一份。
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from ushareiplay.adapters.outbound.appium.soul.online_list_source import SoulOnlineListSource
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.modules.command.domain import CommandCatalogue
from ushareiplay.modules.room.ports import OnlineListSource
from ushareiplay.modules.room.use_cases import PresenceTracker as _PresenceTracker
from ushareiplay.modules.room.use_cases import RoomStateService
from tests.room_support import wire_room_state

_CONTEXT = SimpleNamespace(
    room_state=None,
    presence=None,
    scraper=None,
    proxy=None,
)


@asynccontextmanager
async def _noop_session(_reason: str):
    yield


class _DrawerProxy:
    """延迟解析 `OnlineDrawerManager`：多数抓取测试把 `_scrape...` 打桩了，不碰抽屉。"""

    @property
    def driver(self):
        from ushareiplay.managers.online_drawer import OnlineDrawerManager

        return OnlineDrawerManager.instance().driver

    def drawer_session(self, reason):
        from ushareiplay.managers.online_drawer import OnlineDrawerManager

        return OnlineDrawerManager.instance().drawer_session(reason)


class _ScraperProxy(OnlineListSource):
    """`InfoManager` 拿到的稳定代理：具体 scraper 可以在测试中途重建。"""

    async def refresh_online_users(self, target_count=None) -> bool:
        return await _CONTEXT.scraper.refresh_online_users(target_count)


def reset_context() -> None:
    """每个测试一份新的共享对象（conftest 调用）。"""
    _CONTEXT.room_state = RoomStateService(
        catalogue=CommandCatalogue.from_config(ConfigLoader.load_config())
    )
    _CONTEXT.presence = _PresenceTracker()
    _CONTEXT.proxy = _ScraperProxy()
    _CONTEXT.scraper = None


def room_state() -> RoomStateService:
    return _CONTEXT.room_state


def presence() -> _PresenceTracker:
    return _CONTEXT.presence


def online_list_source() -> OnlineListSource:
    return _CONTEXT.proxy


def _default_party_id(handler):
    config = getattr(handler, "config", None) if handler is not None else None
    if config is None:
        return None
    try:
        if hasattr(config, "value"):
            return config.value("default_party_id")
        section = config.maybe_section("soul") if hasattr(config, "maybe_section") else None
        return section.value("default_party_id") if section is not None else None
    except Exception:
        return None


class RoomState:
    """旧单例 API 的测试替身，背后是共享的 `RoomStateService`。"""

    @classmethod
    def reset_instance(cls):
        state = _CONTEXT.room_state
        state.default_party_id = None
        state._catalogue = None
        state._store = None
        state.clear()

    @classmethod
    def initialize(cls, handler=None, catalogue=None):
        state = _CONTEXT.room_state
        state.default_party_id = _default_party_id(handler)
        if catalogue is not None:
            state.configure_catalogue(catalogue)
        if handler is not None and getattr(handler, "logger", None) is not None:
            state._logger = handler.logger
        wire_room_state(state)
        return state

    @classmethod
    def instance(cls):
        return _CONTEXT.room_state

    @classmethod
    def is_initialized(cls) -> bool:
        return True

    @classmethod
    def in_guest_room(cls) -> bool:
        return bool(_CONTEXT.room_state.is_guest_room)


class PresenceTracker:
    """旧单例 API 的测试替身，背后是共享的 `PresenceTracker`。"""

    @classmethod
    def reset_instance(cls):
        _CONTEXT.presence.clear()

    @classmethod
    def initialize(cls, handler=None):
        if handler is not None and getattr(handler, "logger", None) is not None:
            _CONTEXT.presence._logger = handler.logger
        return _CONTEXT.presence

    @classmethod
    def instance(cls):
        return _CONTEXT.presence

    @classmethod
    def is_initialized(cls) -> bool:
        return True


class OnlineListScraper:
    """旧单例 API 的测试替身：构造真实的 `SoulOnlineListSource`。"""

    @classmethod
    def reset_instance(cls):
        _CONTEXT.scraper = None

    @classmethod
    def initialize(cls, handler=None):
        _CONTEXT.scraper = SoulOnlineListSource(
            drawer=_DrawerProxy(),
            users=TortoiseUserRepository(),
            presence=_CONTEXT.presence,
            room_state=_CONTEXT.room_state,
            ui_session=_noop_session,
            logger=getattr(handler, "logger", None),
        )
        return _CONTEXT.scraper

    @classmethod
    def instance(cls):
        if _CONTEXT.scraper is None:
            cls.initialize()
        return _CONTEXT.scraper
