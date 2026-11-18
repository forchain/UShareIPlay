"""QQ Music 系统级媒体控制出站适配器（暂停/恢复、媒体音量）。"""

import re
from typing import Optional

from ushareiplay.core.driver_decorator import with_driver_recovery
from ushareiplay.modules.playback.ports import PlaybackControlPort


class QQMusicMediaSession(PlaybackControlPort):
    """通过 Appium `mobile: shell` 与按键动作执行媒体暂停/恢复和音量调节。"""

    def __init__(self, handler):
        self._handler = handler

    @property
    def driver(self):
        return self._handler.driver

    @property
    def driver_recovery_context(self):
        return self._handler.driver_recovery_context

    @property
    def logger(self):
        return self._handler.logger

    @with_driver_recovery(retry=False, op="write")
    def pause_resume(self, should_pause: bool) -> dict:
        """暂停或恢复播放 - 系统级控制"""
        action = "暂停" if should_pause else "恢复"
        self.logger.info(f"Attempting to {action} playback")
        self.driver.execute_script(
            "mobile: shell",
            {"command": "input keyevent KEYCODE_MEDIA_PLAY_PAUSE"},
        )
        self.logger.info("Sent media play/pause key event")
        return {"action": action}

    @with_driver_recovery
    def get_volume_level(self) -> Optional[int]:
        """Get current volume level - system level"""
        result = self.driver.execute_script(
            "mobile: shell",
            {"command": "dumpsys audio"},
        )

        if result and isinstance(result, str):
            parts = result.split("- STREAM_MUSIC:")
            if len(parts) > 1:
                match = re.search(r"streamVolume:(\d+)", parts[1])
                if match:
                    volume = int(match.group(1))
                    volume = max(0, min(15, volume))
                    self.logger.info(f"Current volume: {volume}")
                    return volume

        self.logger.warning("Could not parse volume level, using default value 0")
        return 0

    @with_driver_recovery
    def step_volume(self, delta: int) -> None:
        """Press hardware volume keys `abs(delta)` times."""
        times = abs(delta)
        action = (
            self._handler.key_actions.press_volume_down
            if delta < 0
            else self._handler.key_actions.press_volume_up
        )
        self.logger.info(f"{'Decreasing' if delta < 0 else 'Increasing'} volume by {times} steps")
        for i in range(times):
            action()
            self.logger.info(f"{'Decreased' if delta < 0 else 'Increased'} volume ({i + 1}/{times})")
