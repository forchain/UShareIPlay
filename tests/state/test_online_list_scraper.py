import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from ushareiplay.state.online_list_scraper import OnlineListScraper
from ushareiplay.state.online_list_ui import OnlineListUI
from ushareiplay.state.room_state import RoomState
from ushareiplay.state.presence_tracker import PresenceTracker


class FakeOnlineListUI(OnlineListUI):
    """第二个适配器：测试用的 UISeen 端口实现，让 seam 成为真 seam。"""

    def __init__(self):
        self.elements = {}
        self.wait_elements = {}
        self.child_elements = []
        self.child_element_map = {}
        self.swipes = []
        self.clicks = []

    def try_find_element(self, key, log=True):
        return self.elements.get(key)

    def wait_for_element(self, key):
        return self.wait_elements.get(key)

    def find_child_elements(self, parent, key):
        return self.child_elements

    def find_child_element(self, parent, key):
        return self.child_element_map.get(key)

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=300):
        self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))
        return True

    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5):
        self.clicks.append((element, x_ratio, y_ratio))
        return True


@pytest.fixture
def scraper():
    OnlineListScraper.reset_instance()
    s = OnlineListScraper.initialize()
    s._logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    s._ui = FakeOnlineListUI()
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

    ui = scraper._ui
    ui.elements["user_count"] = user_count_elem
    ui.wait_elements["online_users"] = online_container
    ui.wait_elements["bottom_drawer"] = MagicMock()
    ui.child_elements = [user_container]
    ui.child_element_map = {
        "online_user": user_elem,
        "follow_state": follow_state_elem,
    }

    with patch("ushareiplay.dal.user_dao.UserDAO.get_or_create", new=AsyncMock()):
        result = await scraper.refresh_online_users()

    assert result is True
    assert "alice" in presence_tracker.get_online_users()
    assert presence_tracker.get_online_users() == {"alice"}


def test_refresh_online_users_no_op_when_user_count_element_missing(scraper):
    RoomState.initialize()
    PresenceTracker.initialize()
    # Should return early without raising
    result = asyncio.run(scraper.refresh_online_users())
    assert result is False
    assert scraper._ui.swipes == []
    assert scraper._ui.clicks == []


@pytest.mark.asyncio
async def test_online_list_ui_session_default_noop():
    ui = FakeOnlineListUI()
    entered = False
    async with ui.ui_session("test"):
        entered = True
    assert entered is True


@pytest.mark.asyncio
async def test_soul_online_list_ui_session_delegates_to_controller():
    from ushareiplay.state.online_list_ui import SoulOnlineListUI

    mock_controller = MagicMock()
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = None
    mock_session.__aexit__.return_value = None
    mock_controller.ui_session.return_value = mock_session

    mock_handler = MagicMock()
    mock_handler.controller = mock_controller

    ui = SoulOnlineListUI(handler=mock_handler)
    async with ui.ui_session("event:refresh_online_users"):
        pass

    mock_controller.ui_session.assert_called_once_with("event:refresh_online_users")
    mock_session.__aenter__.assert_called_once()
    mock_session.__aexit__.assert_called_once()

