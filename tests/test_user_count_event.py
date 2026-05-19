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
        ("6人在线", 6), # This will fail with current implementation
        ("123", 123),
        ("在线 10 人", 10),
    ]
    
    with patch("ushareiplay.managers.info_manager.InfoManager.instance") as mock_instance:
        mock_info = MagicMock()
        mock_info.user_count = 0
        mock_info.refresh_online_users = AsyncMock()
        mock_instance.return_value = mock_info
        
        for input_text, expected_count in test_cases:
            mock_wrapper.text = input_text
            mock_info.user_count = -1 # Reset to ensure update
            await event.handle("user_count", mock_wrapper)
            assert mock_info.user_count == expected_count, f"Failed to parse '{input_text}'"

@pytest.mark.asyncio
async def test_user_count_parsing_failure():
    mock_handler = MagicMock()
    mock_handler.logger = MagicMock()
    event = UserCountEvent(handler=mock_handler)
    mock_wrapper = MagicMock()
    
    failure_cases = ["", "无数据", "unknown"]
    
    with patch("ushareiplay.managers.info_manager.InfoManager.instance") as mock_instance:
        mock_info = MagicMock()
        mock_info.user_count = 0
        mock_instance.return_value = mock_info
        
        for input_text in failure_cases:
            mock_wrapper.text = input_text
            result = await event.handle("user_count", mock_wrapper)
            assert result is False
            assert mock_info.user_count == 0 # Should not change
