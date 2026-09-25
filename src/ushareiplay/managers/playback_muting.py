from contextlib import contextmanager
from typing import Iterator, Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.state.room_state import RoomState


class PlaybackMuting(Singleton):
    """
    播放静音保护 - 点歌/切歌期间的麦克风生命周期协调器。

    生命周期：配置判定 -> 若开麦则先闭麦 -> 执行播放动作与公屏消息
    -> 等待底层播放就绪 -> 无条件恢复开麦（异常与超时同样兜底）。
    就绪检测由 MusicManager 提供，麦克风状态与恢复由 MicManager 提供
    （见 ADR-0007：接缝是 MicManager.state()/set_active()/ensure_active()）。
    """

    DEFAULT_SETTINGS = {
        "enabled": True,
        "guest_room_only": False,
        "timeout": 5.0,
        "settling_delay": 0.3,
    }

    def __init__(self):
        from ushareiplay.handlers.soul_handler import SoulHandler
        from ushareiplay.managers.mic_manager import MicManager
        from ushareiplay.managers.music_manager import MusicManager
        self.soul_handler = SoulHandler.instance()
        self.music_manager = MusicManager.instance()
        self.mic_manager = MicManager.instance()
        self.logger = self.soul_handler.logger

    @property
    def settings(self) -> dict:
        """soul.playback_mute 配置，缺失或未声明的项回退到默认值。"""
        settings = dict(self.DEFAULT_SETTINGS)
        config = getattr(self.soul_handler, "config", None)
        section = config.get("playback_mute") if isinstance(config, dict) else None
        if isinstance(section, dict):
            settings.update({key: section[key] for key in settings if key in section})
        return settings

    def should_engage(self, settings: dict = None) -> bool:
        """当前房间是否启用静音保护（guest_room_only 时仅他人房间生效）。"""
        settings = self.settings if settings is None else settings
        if not settings["enabled"]:
            return False
        if not settings["guest_room_only"]:
            return True
        return self._is_guest_room()

    @contextmanager
    def guard(self, expected_song: Optional[str] = None) -> Iterator[bool]:
        """点歌/切歌的静音保护上下文。

        with 块内执行点歌、切回房间与公屏消息；退出时等待播放就绪再开麦。
        产出：本次是否实际执行了闭麦点击（未启用或本就闭麦时为 False）。
        """
        settings = self.settings
        if not self.should_engage(settings):
            yield False
            return

        self._playback_failed = False
        muted = self._mute_if_active()
        try:
            yield muted
        except BaseException:
            # 播放异常时立即恢复开麦，不再等待就绪
            self._restore_mic()
            raise

        try:
            if self._playback_failed:
                self.logger.info("Playback failed, restoring microphone immediately")
            else:
                self._wait_until_ready(settings, expected_song)
        finally:
            self._restore_mic()

    def report_failure(self):
        """静音保护期间上报播放失败（如搜不到歌、VIP 限制）。

        以结果而非异常上报的失败同样跳过就绪等待，立即恢复开麦，避免房间
        在错误提示后仍长时间听不到机器人。
        """
        self._playback_failed = True

    def _is_guest_room(self) -> bool:
        if not RoomState.is_initialized():
            return False
        return bool(RoomState.instance().is_guest_room)

    def _mute_if_active(self) -> bool:
        """开麦时点击闭麦；本就闭麦或无法判定时不产生多余的 UI 点击。"""
        if self.mic_manager.state() is not True:
            return False
        result = self.mic_manager.set_active(False)
        if isinstance(result, dict) and result.get("error"):
            self.logger.warning(f"Failed to mute microphone before playback: {result['error']}")
            return False
        self.logger.info("Microphone muted before playback")
        return True

    def _wait_until_ready(self, settings: dict, expected_song: Optional[str]):
        ready = self.music_manager.wait_for_playback_ready(
            expected_song=expected_song,
            timeout=settings["timeout"],
            settling_delay=settings["settling_delay"],
        )
        if not ready:
            self.logger.warning("Playback not ready within timeout, restoring microphone")

    def _restore_mic(self):
        """无条件恢复开麦，保证机器人不会停留在闭麦状态。"""
        try:
            result = self.mic_manager.ensure_active()
            if isinstance(result, dict) and result.get("error"):
                self.logger.error(f"Failed to restore microphone after playback: {result['error']}")
        except Exception as exc:
            self.logger.error(f"Failed to restore microphone after playback: {exc}")
