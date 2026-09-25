import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ushareiplay.events.focus_count import FocusCountEvent, __elements__, __multiple__
from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_singletons():
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()
    RoomState.initialize()
    yield
    SeatObservationManager.reset_instance()
    RoomState.reset_instance()


def test_focus_count_event_metadata():
    assert "focus_count" in __elements__
    assert "seat_desk" in __elements__
    assert __multiple__ is True


@pytest.mark.asyncio
async def test_focus_count_event_handles_focus_count():
    handler = MagicMock()
    handler.logger = MagicMock()
    observation = SeatObservationManager.initialize(handler)
    observation.on_focus_count = AsyncMock()

    event = FocusCountEvent(handler=handler)

    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人专注中"

    # First update: from None to 5
    res = await event.handle("focus_count", mock_wrapper)
    assert res is False
    assert RoomState.instance().focus_count == 5
    observation.on_focus_count.assert_awaited_once_with(None, 5)

    # Second update with same count should be ignored
    observation.on_focus_count.reset_mock()
    res2 = await event.handle("focus_count", mock_wrapper)
    assert res2 is False
    observation.on_focus_count.assert_not_called()

    # Third update with changed count: 6
    mock_wrapper.text = "6"
    res3 = await event.handle("focus_count", mock_wrapper)
    assert res3 is False
    assert RoomState.instance().focus_count == 6
    observation.on_focus_count.assert_awaited_once_with(5, 6)


@pytest.mark.asyncio
async def test_focus_count_event_handles_seat_desk():
    handler = MagicMock()
    handler.logger = MagicMock()
    observation = SeatObservationManager.initialize(handler)
    observation.observe_visible_desks = AsyncMock()

    event = FocusCountEvent(handler=handler)
    event.previous_focus_count = 3

    desk1 = MagicMock()
    desk2 = MagicMock()

    res = await event.handle("seat_desk", [desk1, desk2])
    assert res is False
    observation.observe_visible_desks.assert_awaited_once_with([desk1, desk2], current_focus_count=3)
