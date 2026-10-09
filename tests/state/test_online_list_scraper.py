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
    room_state.user_count = 1

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
        result = await scraper.refresh_online_users()

    assert result is True
    assert "alice" in presence_tracker.get_online_users()
    assert presence_tracker.get_online_users() == {"alice"}


def test_refresh_online_users_no_op_when_user_count_element_missing(scraper):
    RoomState.initialize()
    PresenceTracker.initialize()
    scraper._handler.element_finder.try_find_element.return_value = None
    # Should return early without raising
    import asyncio
    result = asyncio.run(scraper.refresh_online_users())
    assert result is False
    scraper._handler.element_finder.try_find_element.assert_called_once_with("user_count", log=False)


@pytest.mark.asyncio
async def test_refresh_online_users_retries_and_succeeds_when_second_attempt_matches(scraper, reset_singletons):
    """当首次获取人数对不上（例如滚动漏人）时，自动重试一次；若重试人数对上，则成功更新。"""
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

    user_count_elem = MagicMock()
    online_container = MagicMock()
    online_container.location = {"x": 0, "y": 0}
    online_container.size = {"width": 100, "height": 100}

    # 首次抓取只拿到 alice (1人 < 2人)，重试拿到 alice 和 bob (2人 == 2人)
    call_count = 0

    async def mock_scrape(expected_count):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"alice"}, 2
        return {"alice", "bob"}, 2

    with patch.object(scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await scraper.refresh_online_users()

    assert result is True
    assert call_count == 2
    assert presence_tracker.get_online_users() == {"alice", "bob"}


@pytest.mark.asyncio
async def test_refresh_online_users_aborts_when_count_still_mismatches_after_retry(scraper, reset_singletons):
    """当重试后人数依然对不上时，放弃本次更新，不更新 PresenceTracker 并返回 False。"""
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

    call_count = 0

    async def mock_scrape(expected_count):
        nonlocal call_count
        call_count += 1
        return {"alice"}, 2  # 始终只有 1 人，与 2 人不符

    with patch.object(scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await scraper.refresh_online_users()

    assert result is False
    assert call_count == 2
    # 未更新在线用户集合
    assert presence_tracker.get_online_users() == set()


@pytest.mark.asyncio
async def test_refresh_online_users_respects_target_count_parameter(scraper, reset_singletons):
    """传入 target_count 时优先比对该参数。"""
    room_state = RoomState.initialize()
    room_state._logger = SimpleNamespace(info=lambda _msg: None)
    room_state.user_count = 10  # 房间缓存为 10，但本次事件传入 target_count=1

    presence_tracker = PresenceTracker.initialize()
    presence_tracker._logger = SimpleNamespace(
        info=lambda _msg: None,
        debug=lambda _msg: None,
        critical=lambda _msg: None,
        error=lambda _msg: None,
    )

    async def mock_scrape(expected_count):
        assert expected_count == 1
        return {"alice"}, 1

    with patch.object(scraper, "_scrape_online_user_names", side_effect=mock_scrape):
        result = await scraper.refresh_online_users(target_count=1)

    assert result is True
    assert presence_tracker.get_online_users() == {"alice"}


