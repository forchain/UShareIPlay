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
