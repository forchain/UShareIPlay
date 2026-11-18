"""共享内核端口：生产实现与内存替身都必须满足端口契约。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from tests.fakes.fake_clock import FakeClock
from tests.fakes.in_memory_room_messenger import InMemoryRoomMessenger
from tests.fakes.in_memory_ui_session import InMemoryUISession
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.adapters.outbound.appium.soul.message_dispatch import MessageDispatch
from ushareiplay.core.ui_session_lease import UISessionLease
from ushareiplay.modules.shared.ports import Clock, RoomMessenger, UISession


def test_message_dispatch_is_the_room_messenger_production_implementation():
    assert issubclass(MessageDispatch, RoomMessenger)
    assert MessageDispatch.__abstractmethods__ == frozenset()


def test_ui_session_lease_is_the_ui_session_production_implementation():
    lease = UISessionLease()

    assert isinstance(lease, UISession)
    assert UISessionLease.__abstractmethods__ == frozenset()


def test_system_clock_is_the_clock_production_implementation():
    clock = SystemClock()

    assert isinstance(clock, Clock)
    assert isinstance(clock.now(), datetime)


@pytest.mark.asyncio
async def test_system_clock_sleeps():
    await SystemClock().sleep(0)


def test_in_memory_room_messenger_satisfies_the_port_and_honours_silent():
    messenger = InMemoryRoomMessenger()

    assert isinstance(messenger, RoomMessenger)

    messenger.send_screen_message("hello")
    messenger.send_screen_message("shh", silent=True)

    assert messenger.messages == ["hello"]
    assert messenger.suppressed == ["shh"]


def test_fake_clock_satisfies_the_port():
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))

    assert isinstance(clock, Clock)
    assert clock.now() == datetime(2026, 1, 1, 12, 0, 0)


def test_fake_clock_advances_on_sleep_and_manual_advance():
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0))

    asyncio.run(clock.sleep(90))
    clock.advance(30)

    assert clock.now() == datetime(2026, 1, 1, 12, 0, 0) + timedelta(seconds=120)
    assert clock.sleeps == [90]


@pytest.mark.asyncio
async def test_in_memory_ui_session_holds_and_releases():
    session = InMemoryUISession()

    assert isinstance(session, UISession)
    assert not session.holds_session

    async with session.acquire("scan") as held:
        assert held is True
        assert session.holds_session
        assert not session.busy_elsewhere

    assert not session.holds_session
    assert session.reasons == ["scan"]


@pytest.mark.asyncio
async def test_in_memory_ui_session_skips_when_busy_elsewhere():
    session = InMemoryUISession()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with session.acquire("holder"):
            entered.set()
            await release.wait()

    holder_task = asyncio.create_task(holder())
    await entered.wait()

    async with session.acquire("scan", skip_if_busy=True) as held:
        assert held is False
    assert session.busy_elsewhere is True

    release.set()
    await holder_task


@pytest.mark.asyncio
async def test_in_memory_ui_session_is_reentrant_for_the_same_task():
    session = InMemoryUISession()

    async with session.acquire("outer") as outer:
        async with session.acquire("inner") as inner:
            assert outer is True and inner is True
            assert session.holds_session

    assert not session.holds_session
    assert session.reasons == ["outer"]
