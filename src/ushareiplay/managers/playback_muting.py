import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from ushareiplay.core.roles import RolePolicy
from ushareiplay.core.singleton import Singleton
from ushareiplay.state.room_state import RoomState


class PlaybackMuting(Singleton):
    """
    播放静音保护 - 点歌/切歌期间的麦克风生命周期协调器。

    生命周期：配置判定 -> 若开麦则先闭麦 -> 执行播放动作与公屏消息
    -> 等待底层播放就绪 -> 无条件恢复开麦（异常与超时同样兜底）。
    就绪检测由 MusicManager 提供，麦克风状态与恢复由 MicManager 提供
    （见 ADR-0007：接缝是 MicManager.state()/set_active()/ensure_active()）。

    是否生效由两层决定：配置（`enabled` / `guest_room_only`）是常态策略，
    `arm_on_mic()` 是有人上麦时的运行时救场 —— 麦上有人时切歌底噪会盖住他，
    因此此时无条件保护，房间生命周期（RoomState.clear()）再把它重置。
    """

    DEFAULT_SETTINGS = {
        "enabled": True,
        "guest_room_only": False,
        "auto_enable_on_mic": True,
        "ignore_users": (),
        "timeout": 5.0,
        "settling_delay": 0.3,
    }

    #: 运行时开启状态的兜底默认值；`__init__` 会在实例上落一份。
    _dynamic_enabled = False

    def __init__(self, handler=None, music_manager=None, mic_manager=None):
        from ushareiplay.managers.mic_manager import MicManager
        from ushareiplay.managers.music_manager import MusicManager
        self.soul_handler = handler
        self.music_manager = music_manager or (MusicManager.instance() if MusicManager.is_initialized() else None)
        self.mic_manager = mic_manager or (MicManager.instance() if MicManager.is_initialized() else None)
        self.logger = getattr(handler, "logger", None) or logging.getLogger("PlaybackMuting")
        self._dynamic_enabled = False

    @property
    def settings(self) -> dict:
        """soul.playback_mute 配置，缺失或未声明的项回退到默认值。

        配置写在 `soul.playback_mute` 下（见 config.yaml），顶层 `playback_mute`
        只作为扁平写法的回落：只读顶层键会让整节配置静默取默认值。
        """
        settings = dict(self.DEFAULT_SETTINGS)
        config = getattr(self.soul_handler, "config", None)
        section = None
        if isinstance(config, dict):
            soul_cfg = config.get("soul")
            if isinstance(soul_cfg, dict):
                section = soul_cfg.get("playback_mute")
            if not isinstance(section, dict):
                section = config.get("playback_mute")
        if isinstance(section, dict):
            settings.update({key: section[key] for key in settings if key in section})
        return settings

    @property
    def dynamically_enabled(self) -> bool:
        """是否因有人上麦而运行时开启（配置之外的状态）。"""
        return self._dynamic_enabled

    def should_engage(self, settings: dict = None) -> bool:
        """当前房间是否启用静音保护。

        运行时开启时无条件生效：配置里的 `enabled` / `guest_room_only` 描述的是
        常态策略，救场由联动负责（`auto_enable_on_mic` 才是联动行为的总开关）。
        """
        settings = self.settings if settings is None else settings
        if self._dynamic_enabled:
            return True
        if not settings["enabled"]:
            return False
        if not settings["guest_room_only"]:
            return True
        return RoomState.in_guest_room()

    # ------------------------------------------------------------------
    # 运行时开启：有人上麦时救场
    # ------------------------------------------------------------------

    def enable(self, reason: str = "") -> bool:
        """运行时开启静音保护；返回本次调用是否改变了状态。"""
        if self._dynamic_enabled:
            return False
        self._dynamic_enabled = True
        suffix = f": {reason}" if reason else ""
        self.logger.info(f"Playback muting enabled at runtime{suffix}")
        return True

    def arm_on_mic(self, nickname: str) -> bool:
        """有人上麦时的联动入口：总开关、自身与忽略名单的判定都归这里。

        读配置的是本模块，因此调用方（MessageManager）只负责把事件递进来。
        """
        if not self.settings["auto_enable_on_mic"]:
            return False
        name = (nickname or "").strip()
        if not name or self._is_ignored(name):
            self.logger.debug(f"Playback muting not armed for on-mic user '{name}'")
            return False
        return self.enable(reason=f"'{name}' 已上麦")

    def reset(self) -> None:
        """房间生命周期重置：丢掉运行时开启状态，不跨场次、跨会话。"""
        if self._dynamic_enabled:
            self._dynamic_enabled = False
            self.logger.info("Playback muting runtime enable reset for the new room")

    def _is_ignored(self, nickname: str) -> bool:
        """自身账号与配置指定的系统账号不触发联动。"""
        normalized = nickname.strip().lower()
        if normalized in self._own_accounts():
            return True
        ignored = self.settings["ignore_users"] or ()
        return normalized in {str(name).strip().lower() for name in ignored}

    def _own_accounts(self) -> set[str]:
        """机器人自己的 Soul 账号：配置的 room_owner。

        机器人以该账号在房间里发言（见 roles.py 的身份约定），它自己上麦
        不构成「别人在麦上」，否则一次抢麦就把静音保护永久锁死。
        """
        config = getattr(self.soul_handler, "config", None)
        owner = RolePolicy(config if isinstance(config, dict) else None).configured_room_owner
        return {owner.strip().lower()} if owner else set()

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
