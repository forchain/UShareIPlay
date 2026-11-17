"""UISessionLease 的独立单元测试：不构造 AppController。"""

import asyncio
from unittest.mock import MagicMock

import pytest

from ushareiplay.core.ui_session_lease import UISessionLease


@pytest.mark.asyncio
async def test_same_task_acquisition_is_reentrant_and_counted():
    lease = UISessionLease()

    async with lease.acquire("outer") as held:
        assert held is True
        assert lease.holds_session is True
        assert lease.busy_elsewhere is False
        assert lease.lock.locked() is True

        async with lease.acquire("inner") as nested:
            assert nested is True
            assert lease.holds_session is True

        assert lease.holds_session is True

    assert lease.holds_session is False
    assert lease.lock.locked() is False


@pytest.mark.asyncio
async def test_cross_task_holder_reports_busy_and_skip_if_busy_returns_false():
    lease = UISessionLease()
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with lease.acquire("holder"):
            started.set()
            await release.wait()

    task = asyncio.create_task(holder())
    await started.wait()

    assert lease.holds_session is False
    assert lease.busy_elsewhere is True

    async with lease.acquire("probe", skip_if_busy=True) as held:
        assert held is False

    release.set()
    await task
    assert lease.lock.locked() is False


@pytest.mark.asyncio
async def test_skip_if_busy_still_acquires_when_free():
    lease = UISessionLease()

    async with lease.acquire("probe", skip_if_busy=True) as held:
        assert held is True
        assert lease.holds_session is True


@pytest.mark.asyncio
async def test_pause_gate_cancels_even_a_reentrant_acquisition():
    paused = {"value": True}
    lease = UISessionLease(is_paused=lambda: paused["value"])

    with pytest.raises(asyncio.CancelledError):
        async with lease.acquire("blocked"):
            pass

    paused["value"] = False
    async with lease.acquire("outer"):
        paused["value"] = True
        with pytest.raises(asyncio.CancelledError):
            async with lease.acquire("nested-blocked"):
                pass


@pytest.mark.asyncio
async def test_logs_acquire_and_release_at_debug_level():
    logger = MagicMock()
    lease = UISessionLease(logger=lambda: logger)

    async with lease.acquire("seat_inspect"):
        pass

    logger.debug.assert_any_call("[ui_lock] acquired: seat_inspect")
    logger.debug.assert_any_call("[ui_lock] released: seat_inspect")
