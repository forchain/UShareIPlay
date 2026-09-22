import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from ushareiplay.events.user_count import UserCountEvent


@pytest.mark.asyncio
async def test_user_count_parsing_formats():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    event = UserCountEvent(handler=mock_handler)
    mock_wrapper = MagicMock()

    test_cases = [
        ("6人", 6),
        ("6人在线", 6),  # This will fail with current implementation
        ("123", 123),
        ("在线 10 人", 10),
    ]

    with (
        patch("ushareiplay.state.room_state.RoomState.instance") as mock_room_state_instance,
        patch("ushareiplay.state.online_list_scraper.OnlineListScraper.instance") as mock_scraper_instance,
    ):
        mock_room_state = MagicMock()
        mock_room_state.user_count = 0
        mock_room_state_instance.return_value = mock_room_state

        mock_scraper = MagicMock()
        mock_scraper.refresh_online_users = AsyncMock()
        mock_scraper_instance.return_value = mock_scraper

        for input_text, expected_count in test_cases:
            mock_wrapper.text = input_text
            mock_room_state.user_count = -1  # Reset to ensure update
            await event.handle("user_count", mock_wrapper)
            assert mock_room_state.user_count == expected_count, f"Failed to parse '{input_text}'"


@pytest.mark.asyncio
async def test_user_count_parsing_failure():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    event = UserCountEvent(handler=mock_handler)
    mock_wrapper = MagicMock()

    failure_cases = ["", "无数据", "unknown"]

    with (
        patch("ushareiplay.state.room_state.RoomState.instance") as mock_room_state_instance,
        patch("ushareiplay.state.online_list_scraper.OnlineListScraper.instance") as mock_scraper_instance,
    ):
        mock_room_state = MagicMock()
        mock_room_state.user_count = 0
        mock_room_state_instance.return_value = mock_room_state

        mock_scraper = MagicMock()
        mock_scraper_instance.return_value = mock_scraper

        for input_text in failure_cases:
            mock_wrapper.text = input_text
            result = await event.handle("user_count", mock_wrapper)
            assert result is False
            assert mock_room_state.user_count == 0  # Should not change


@pytest.mark.asyncio
async def test_user_count_retries_when_refresh_fails():
    """
    当首次刷新在线列表失败（例如界面正在处理弹窗/命令导致未找到元素）时，
    后续帧检测到人数仍不一致时应继续重试刷新，而不是因为提前更新了 room_state.user_count
    而永远放弃重试，导致在线人数列表卡死直至下一个不同人数出现（跳变）。
    """
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    event = UserCountEvent(handler=mock_handler)
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    from ushareiplay.state.room_state import RoomState
    from ushareiplay.state.online_list_scraper import OnlineListScraper

    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()

    # Frame 1: 刷新失败（例如 try_find_element 返回 None，或返回 False）
    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=False)) as mock_refresh:
        await event.handle("user_count", mock_wrapper)
        assert mock_refresh.call_count == 1
        # 如果刷新失败，room_state.user_count 不应该认为已经成功同步为 5
        # 否则 Frame 2 将永远无法触发刷新
        assert room_state.user_count != 5, "room_state.user_count was prematurely updated on failure"

    # Frame 2: UI 空闲，再次收到相同的 "5人"
    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=True)) as mock_refresh_2:
        await event.handle("user_count", mock_wrapper)
        # 应该重试刷新
        assert mock_refresh_2.call_count == 1, "refresh_online_users was not retried after previous failure"
        # 成功后才同步为 5
        assert room_state.user_count == 5


@pytest.mark.asyncio
async def test_user_count_deferred_when_ui_busy():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    mock_runtime = MagicMock()
    mock_runtime.is_ui_busy.return_value = True

    event = UserCountEvent(handler=mock_handler, runtime=mock_runtime)
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    from ushareiplay.state.room_state import RoomState
    from ushareiplay.state.online_list_scraper import OnlineListScraper

    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()

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
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    event = UserCountEvent(handler=mock_handler)
    mock_wrapper = MagicMock()
    mock_wrapper.text = "5人"

    from ushareiplay.state.room_state import RoomState
    from ushareiplay.state.online_list_scraper import OnlineListScraper

    RoomState.reset_instance()
    OnlineListScraper.reset_instance()

    room_state = RoomState.initialize()
    room_state._logger = MagicMock()
    room_state.user_count = 4

    scraper = OnlineListScraper.initialize()
    scraper._logger = MagicMock()

    with patch.object(scraper, "refresh_online_users", new=AsyncMock(return_value=False)) as mock_refresh:
        for _ in range(9):
            await event.handle("user_count", mock_wrapper)
            assert room_state.user_count == 4

        # 10th failure triggers fallback
        await event.handle("user_count", mock_wrapper)
        assert room_state.user_count == 5


