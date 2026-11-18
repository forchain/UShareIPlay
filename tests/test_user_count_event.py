import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

from ushareiplay.adapters.inbound.ui_events.user_count import UserCountEvent
from tests import legacy_state
from tests.legacy_state import OnlineListScraper, PresenceTracker, RoomState


def _event(scraper=None, runtime=None):
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.controller = SimpleNamespace(
        room_state=RoomState.instance(),
        presence=PresenceTracker.instance(),
        online_list_source=scraper or legacy_state.online_list_source(),
    )
    return UserCountEvent(handler=handler, runtime=runtime)


@pytest.mark.asyncio
async def test_user_count_parsing_formats():
    room_state = RoomState.initialize()
    room_state.user_count = 0
    scraper = MagicMock()
    scraper.refresh_online_users = AsyncMock()
    event = _event(scraper)
    mock_wrapper = MagicMock()

    test_cases = [
        ("6人", 6),
        ("6人在线", 6),  # This will fail with current implementation
        ("123", 123),
        ("在线 10 人", 10),
    ]

    for input_text, expected_count in test_cases:
        mock_wrapper.text = input_text
        room_state.user_count = -1  # Reset to ensure update
        await event.handle("user_count", mock_wrapper)
        assert room_state.user_count == expected_count, f"Failed to parse '{input_text}'"


@pytest.mark.asyncio
async def test_user_count_parsing_failure():
    room_state = RoomState.initialize()
    room_state.user_count = 0
    scraper = MagicMock()
    event = _event(scraper)
    mock_wrapper = MagicMock()

    failure_cases = ["", "无数据", "unknown"]

    for input_text in failure_cases:
        mock_wrapper.text = input_text
        result = await event.handle("user_count", mock_wrapper)
        assert result is False
        assert room_state.user_count == 0  # Should not change


@pytest.mark.asyncio
async def test_user_count_retries_when_refresh_fails():
    """刷新失败时不得提前写 room_state，否则同样的「5人」再也不会触发重试。"""
    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()
    event = _event(legacy_state.online_list_source())
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    # Frame 1: 刷新失败
    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=False)) as mock_refresh:
        await event.handle("user_count", mock_wrapper)
        assert mock_refresh.call_count == 1
        assert room_state.user_count != 5, "room_state.user_count was prematurely updated on failure"

    # Frame 2: UI 空闲，再次收到相同的 "5人"
    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh_2:
        await event.handle("user_count", mock_wrapper)
        assert mock_refresh_2.call_count == 1, "refresh_online_users was not retried after previous failure"
        assert room_state.user_count == 5


@pytest.mark.asyncio
async def test_user_count_deferred_when_ui_busy():
    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.is_ui_busy.return_value = True
    event = _event(legacy_state.online_list_source(), runtime=mock_runtime)
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh:
        result = await event.handle("user_count", mock_wrapper)
        assert result is False
        assert mock_refresh.call_count == 0, "Should not refresh online users when UI is busy"
        assert room_state.user_count == 4, "Should not update room_state.user_count when UI is busy"

    # Now UI becomes idle
    mock_runtime.is_ui_busy.return_value = False
    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh:
        result = await event.handle("user_count", mock_wrapper)
        assert mock_refresh.call_count == 1
        assert room_state.user_count == 5


@pytest.mark.asyncio
async def test_user_count_fallback_after_consecutive_failures():
    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()
    event = _event(legacy_state.online_list_source())
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=False)):
        for _ in range(9):
            await event.handle("user_count", mock_wrapper)
            assert room_state.user_count == 4

        # 10th failure triggers fallback
        await event.handle("user_count", mock_wrapper)
        assert room_state.user_count == 5


@pytest.mark.asyncio
async def test_user_count_refreshes_when_presence_is_empty_even_if_count_matches():
    """人数一致但在线列表为空（初次启动 / 刷新一直失败）时仍要抓取。"""
    RoomState.reset_instance()
    PresenceTracker.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 5  # 人数与当前一致

    presence_tracker = PresenceTracker.initialize()
    presence_tracker._logger = MagicMock()

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()
    event = _event(legacy_state.online_list_source())
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh:
        result = await event.handle("user_count", mock_wrapper)
        assert mock_refresh.call_count == 1, "Should trigger refresh when presence list is empty"


@pytest.mark.asyncio
async def test_user_count_skips_when_presence_exists_and_count_matches():
    """人数未变化且在线列表已有数据时跳过刷新。"""
    RoomState.reset_instance()
    PresenceTracker.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 5

    presence_tracker = PresenceTracker.initialize()
    presence_tracker._logger = MagicMock()
    presence_tracker.update_online_users(["alice", "bob", "cathy", "david", "eva"])

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()
    event = _event(legacy_state.online_list_source())
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh:
        result = await event.handle("user_count", mock_wrapper)
        assert mock_refresh.call_count == 0, "Should skip refresh when presence exists and count matches"
