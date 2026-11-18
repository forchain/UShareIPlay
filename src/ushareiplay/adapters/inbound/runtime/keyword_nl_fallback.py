"""未命中关键字时的自然语言兜底：拼装上下文后调用现有解析器。

解析器本身是 #548 的迁移范围；这里只保留组合根可注入的接缝
（构造函数第二个参数），默认由根配置惰性构造。
"""

from typing import Optional

from ushareiplay.modules.command.domain import NaturalLanguageResult
from ushareiplay.modules.command.ports import NaturalLanguageFallback
from ushareiplay.modules.shared.config import ConfigView


def _as_root_view(config) -> ConfigView:
    if isinstance(config, ConfigView):
        return config
    return ConfigView(config or {})


class NaturalLanguageFallbackAdapter(NaturalLanguageFallback):
    def __init__(self, config=None, resolver=None, memory=None):
        self._config = config
        self._nl_resolver = resolver
        self._memory = memory

    @property
    def config(self) -> ConfigView:
        return _as_root_view(self._config)

    @property
    def nl_resolver(self):
        """惰性获取 NaturalLanguageResolver；测试可直接替换 `_nl_resolver`。"""
        if self._nl_resolver is None:
            from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
                OpenAICompatibleNaturalLanguageResolver,
            )
            from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage

            root_cfg = self.config
            llm_section = root_cfg.maybe_section("llm")
            cfg = dict(llm_section.data) if llm_section else {}
            if "system_users" not in cfg:
                soul = root_cfg.maybe_section("soul")
                sys_users = (soul.value("system_users") if soul else None) or root_cfg.value(
                    "system_users"
                )
                if sys_users:
                    cfg["system_users"] = sys_users
            self._nl_resolver = ResolveNaturalLanguage(
                OpenAICompatibleNaturalLanguageResolver(cfg), cfg
            )
        return self._nl_resolver

    async def resolve(
        self, *, user_text: str, user_name: str, user_level: int
    ) -> Optional[NaturalLanguageResult]:
        commands_config = self.config.command_entries
        catalogue = None
        try:
            from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager

            if CommandManager.is_initialized():
                catalogue = CommandManager.instance().catalogue
        except Exception:
            pass

        room_info = None
        try:
            from ushareiplay.state.room_state import RoomState

            room_state = RoomState.instance()
            room_info = {
                "is_guest_room": room_state.is_guest_room,
                "room_id": room_state.room_id,
                "user_count": room_state.user_count,
                "focus_count": room_state.focus_count,
                "recommendation_enabled": room_state.recommendation_enabled,
            }
            if room_state.is_guest_room:
                commands_config = [
                    cmd
                    for cmd in commands_config
                    if room_state.is_command_allowed_in_guest_room(cmd.get("prefix", ""))
                ]
        except Exception:
            pass

        memory_context = None
        try:
            if self._memory is not None:
                memory_context = await self._memory.dialogue_context(
                    user_name, user_level=user_level
                )
        except Exception:
            pass

        resolved = await self.nl_resolver.resolve(
            user_text=user_text,
            user_name=user_name,
            user_level=user_level,
            commands_config=commands_config,
            playback_info=self._get_playback_info(),
            room_info=room_info,
            memory_context=memory_context,
            command_catalogue=catalogue,
        )
        if not resolved or not resolved.content:
            return None
        return resolved

    def _get_playback_info(self) -> Optional[dict]:
        """获取当前活跃的播放与歌单信息缓存。"""
        info = {}
        try:
            from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster

            broadcaster = PlaybackBroadcaster.instance()
            if broadcaster and broadcaster._playback_info_cache:
                info.update(broadcaster._playback_info_cache)
        except Exception:
            pass

        try:
            from ushareiplay.managers.playlist_session import PlaylistSession

            playlist_state = PlaylistSession.instance()
            if playlist_state:
                if playlist_state.player_name:
                    info["player"] = playlist_state.player_name
                if playlist_state.current_playlist_name:
                    info["playlist_name"] = playlist_state.current_playlist_name
        except Exception:
            pass

        try:
            from ushareiplay.handlers.qq_music_handler import QQMusicHandler
            from ushareiplay.managers.playlist_session import PlaylistSession

            music_handler = QQMusicHandler.instance()
            if music_handler:
                list_mode = PlaylistSession.instance().list_mode
                if list_mode:
                    playlist_type_map = {
                        "singer": "歌手",
                        "playlist": "歌单",
                        "album": "专辑",
                        "radio": "电台",
                        "favorites": "收藏",
                        "radar": "雷达",
                        "unknown": "未知",
                    }
                    info["playlist_type"] = playlist_type_map.get(list_mode, list_mode)
                play_mode_key = music_handler.play_mode_key
                if play_mode_key:
                    info["play_mode"] = music_handler.play_mode_key_to_name(play_mode_key)
        except Exception:
            pass

        return info if info else None
