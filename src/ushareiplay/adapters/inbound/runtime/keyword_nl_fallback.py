"""未命中关键字时的自然语言兜底：拼装上下文后调用 #548 的解析用例。

所有上下文来源都由构造函数注入（组合根装配），本模块不认识任何 manager /
state 单例，也不读取私有缓存字段。
"""

from dataclasses import dataclass
from typing import Callable, Optional

from ushareiplay.modules.command.domain import NaturalLanguageResult
from ushareiplay.modules.command.ports import NaturalLanguageFallback


@dataclass(frozen=True)
class RoomInfo:
    """提示词需要的房间快照；`allows_command` 为 None 表示不做客房过滤。"""

    is_guest_room: bool
    room_id: Optional[str] = None
    user_count: Optional[int] = None
    focus_count: Optional[int] = None
    recommendation_enabled: Optional[bool] = None
    allows_command: Optional[Callable[[str], bool]] = None

    def as_prompt_context(self) -> dict:
        return {
            "is_guest_room": self.is_guest_room,
            "room_id": self.room_id,
            "user_count": self.user_count,
            "focus_count": self.focus_count,
            "recommendation_enabled": self.recommendation_enabled,
        }


class RoomInfoProvider:
    """从注入的 RoomState 读取快照；未提供 RoomState 时返回 None。"""

    def __init__(self, room_state=None):
        self._room_state = room_state

    def __call__(self) -> Optional[RoomInfo]:
        state = self._room_state
        if state is None:
            return None
        try:
            return RoomInfo(
                is_guest_room=state.is_guest_room,
                room_id=state.room_id,
                user_count=state.user_count,
                focus_count=state.focus_count,
                recommendation_enabled=state.recommendation_enabled,
                allows_command=state.is_command_allowed_in_guest_room,
            )
        except Exception:
            # 房间状态只是提示词的附加上下文；读不到时按「无房间信息」继续解析。
            return None


class PlaybackInfoProvider:
    """从注入的广播缓存 / 歌单上下文 / 音乐 handler 拼装播放快照。"""

    _PLAYLIST_TYPE_NAMES = {
        "singer": "歌手",
        "playlist": "歌单",
        "album": "专辑",
        "radio": "电台",
        "favorites": "收藏",
        "radar": "雷达",
        "unknown": "未知",
    }

    def __init__(self, broadcaster=None, playlist=None, music_handler=None):
        self._broadcaster = broadcaster
        self._playlist = playlist
        self._music_handler = music_handler

    def __call__(self) -> Optional[dict]:
        info = {}
        if self._broadcaster is not None:
            cached = self._broadcaster.get_playback_info_cache()
            if cached:
                info.update(cached)

        if self._playlist is not None:
            if self._playlist.player_name:
                info["player"] = self._playlist.player_name
            if self._playlist.current_playlist_name:
                info["playlist_name"] = self._playlist.current_playlist_name

        if self._music_handler is not None:
            if self._playlist is not None and self._playlist.list_mode:
                info["playlist_type"] = self._PLAYLIST_TYPE_NAMES.get(
                    self._playlist.list_mode, self._playlist.list_mode
                )
            if self._music_handler.play_mode_key:
                info["play_mode"] = self._music_handler.play_mode_key_to_name(
                    self._music_handler.play_mode_key
                )

        return info or None


class NaturalLanguageFallbackAdapter(NaturalLanguageFallback):
    def __init__(
        self,
        *,
        commands_config: Callable[[], list[dict]],
        catalogue: Callable[[], Optional[object]],
        room_info: Callable[[], Optional[RoomInfo]],
        playback_info: Callable[[], Optional[dict]],
        resolver,
        memory=None,
    ):
        self._commands_config = commands_config
        self._catalogue = catalogue
        self._room_info = room_info
        self._playback_info = playback_info
        self._resolver = resolver
        self._memory = memory

    async def resolve(
        self, *, user_text: str, user_name: str, user_level: int
    ) -> Optional[NaturalLanguageResult]:
        room = self._room_info()
        commands_config = list(self._commands_config())
        if room is not None and room.is_guest_room and room.allows_command is not None:
            commands_config = [
                cmd
                for cmd in commands_config
                if room.allows_command(cmd.get("prefix", ""))
            ]

        memory_context = None
        if self._memory is not None:
            try:
                memory_context = await self._memory.dialogue_context(
                    user_name, user_level=user_level
                )
            except Exception:
                # 长期记忆只是提示词的附加上下文；读取失败不应吞掉整条自然语言回复。
                memory_context = None

        resolved = await self._resolver.resolve(
            user_text=user_text,
            user_name=user_name,
            user_level=user_level,
            commands_config=commands_config,
            playback_info=self._playback_info(),
            room_info=room.as_prompt_context() if room is not None else None,
            memory_context=memory_context,
            command_catalogue=self._catalogue(),
        )
        if not resolved or not resolved.content:
            return None
        return resolved
