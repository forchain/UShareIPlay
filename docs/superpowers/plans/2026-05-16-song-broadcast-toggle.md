# Song Broadcast Toggle & Info Command Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configuration to toggle song broadcasting and include song info in the `info` command.

**Architecture:**
1. Update `config.yaml` with the new toggle and update the `info` command template.
2. Update `InfoManager` to respect the new toggle.
3. Create a test to verify the logic.

**Tech Stack:** Python, YAML, Pytest.

---

### Task 1: Configuration Update

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Add `broadcast_playing_info` to `config.yaml`**

Add `broadcast_playing_info: true` under the `soul:` section.

- [ ] **Step 2: Update `info` command template in `config.yaml`**

Modify the `response_template` for the `info` command to include song details at the bottom.

```yaml
   - prefix: "info"
     level: 0
     response_template: "播放模式: {play_mode}\n{current_playlist}\n{online_users}\n{party_duration}\n{song} - {singer} • {album}"
     error_template: "Failed to get playback info, because {error}"
```

### Task 2: InfoManager Logic Update

**Files:**
- Modify: `src/ushareiplay/managers/info_manager.py`

- [ ] **Step 1: Update `send_playing_message` to respect the toggle**

```python
    def send_playing_message(self):
        info = self.get_playback_info_cache()
        if info is None:
            return

        # 检查歌曲信息是否有效
        if 'error' not in info and all(key in info for key in ['song', 'singer', 'album']):
            # 检查是否开启了广播
            broadcast_enabled = self.handler.config.get('soul', {}).get('broadcast_playing_info', True)
            if not broadcast_enabled:
                self.logger.info("Song broadcast is disabled in config, skipping message")
                return

            # 检查是否需要跳过低质量歌曲
            from ushareiplay.handlers.qq_music_handler import QQMusicHandler
            music_handler = QQMusicHandler.instance()
            song_skipped = music_handler.handle_song_quality_check(info)

            # 只有在没有跳过歌曲的情况下才发送播放消息
            if not song_skipped:
                self.handler.send_message(
                    f"{info['song']} - {info['singer']} • {info['album']}")
```

### Task 3: Automated Testing

**Files:**
- Create: `tests/test_info_broadcast.py`

- [ ] **Step 1: Write tests for `InfoManager.send_playing_message`**

```python
import pytest
from unittest.mock import MagicMock, patch
from ushareiplay.managers.info_manager import InfoManager

@pytest.mark.asyncio
async def test_send_playing_message_broadcast_enabled():
    # Setup
    info_manager = InfoManager.instance()
    info_manager._playback_info_cache = {
        'song': 'Test Song',
        'singer': 'Test Singer',
        'album': 'Test Album'
    }
    
    mock_soul_handler = MagicMock()
    mock_soul_handler.config = {'soul': {'broadcast_playing_info': True}}
    
    with patch('ushareiplay.handlers.soul_handler.SoulHandler.instance', return_value=mock_soul_handler), \
         patch('ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance') as mock_qq_handler_class:
        
        mock_qq_handler = mock_qq_handler_class.return_value
        mock_qq_handler.handle_song_quality_check.return_value = False
        
        # Action
        info_manager.send_playing_message()
        
        # Verify
        mock_soul_handler.send_message.assert_called_with("Test Song - Test Singer • Test Album")

@pytest.mark.asyncio
async def test_send_playing_message_broadcast_disabled():
    # Setup
    info_manager = InfoManager.instance()
    info_manager._playback_info_cache = {
        'song': 'Test Song',
        'singer': 'Test Singer',
        'album': 'Test Album'
    }
    
    mock_soul_handler = MagicMock()
    mock_soul_handler.config = {'soul': {'broadcast_playing_info': False}}
    
    with patch('ushareiplay.handlers.soul_handler.SoulHandler.instance', return_value=mock_soul_handler), \
         patch('ushareiplay.handlers.qq_music_handler.QQMusicHandler.instance') as mock_qq_handler_class:
        
        mock_qq_handler = mock_qq_handler_class.return_value
        
        # Action
        info_manager.send_playing_message()
        
        # Verify
        mock_soul_handler.send_message.assert_not_called()
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_info_broadcast.py`
Expected: PASS

### Task 4: Cleanup and Final Check

- [ ] **Step 1: Final verification of `info` command output**

Manual check of `config.yaml` to ensure the template is correct.
Verify that `broadcast_playing_info` is properly placed.
