from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.room_state import RoomState
from ushareiplay.state.presence_tracker import PresenceTracker


@pytest.fixture
def scraper():
    OnlineListScraper.reset_instance()
    s = OnlineListScraper.initialize()
    s._logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    s._handler = MagicMock()
    return s


@pytest.fixture
def reset_singletons():
    RoomState.reset_instance()
    PresenceTracker.reset_instance()


@pytest.mark.asyncio
async def test_refresh_online_users_parses_and_updates_presence(scraper, reset_singletons):
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    room_state.user_count = 2

    presence_tracker = PresenceTracker.initialize()
    presence_tracker._logger = SimpleNamespace(
        info=lambda _msg: None,
        debug=lambda _msg: None,
        critical=lambda _msg: None,
        error=lambda _msg: None,
    )

    # Mock UI elements
    user_count_elem = MagicMock()
    online_container = MagicMock()
    online_container.location = {"x": 0, "y": 0}
    online_container.size = {"width": 100, "height": 100}

    user_container = MagicMock()
    user_elem = MagicMock()
    user_elem.text = "alice"
    follow_state_elem = MagicMock()
    follow_state_elem.text = ""

    scraper._handler.element_finder.try_find_element.side_effect = lambda key, **kwargs: {
        "user_count": user_count_elem,
        "online_users": online_container,
        "bottom_drawer": MagicMock(),
    }.get(key)
    scraper._handler.element_finder.find_child_elements.return_value = [user_container]
    scraper._handler.element_finder.find_child_element.side_effect = lambda parent, key, **kwargs: {
        "online_user": user_elem,
        "follow_state": follow_state_elem,
    }.get(key)
    scraper._handler.element_finder.wait_for_element.side_effect = lambda key: {
        "online_users": online_container,
        "bottom_drawer": MagicMock(),
    }.get(key)

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new=AsyncMock()):
        await scraper.refresh_online_users()

    assert "alice" in presence_tracker.get_online_users()
    assert presence_tracker.get_online_users() == {"alice"}


def test_refresh_online_users_no_op_when_user_count_element_missing(scraper):
    RoomState.initialize()
    PresenceTracker.initialize()
    scraper._handler.element_finder.try_find_element.return_value = None
    # Should return early without raising
    import asyncio
    asyncio.run(scraper.refresh_online_users())
    scraper._handler.element_finder.try_find_element.assert_called_once_with("user_count", log=False)
