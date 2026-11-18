"""歌单会话深模块：Playlist Context、Next Queue 与 Playlist Guard 的唯一所有者。

原先这三件事散在三处：`list_mode` 存在 QQ Music UI 适配器上，`player_name` /
`current_playlist_name` / Next Queue 存在 `PlaylistState` 里，守护规则又分别落在
`PlaylistAdoption` 与 `InfoManager`。UI 适配器不该持有房间播放状态，调用方也不该
绕过采纳/守护边界，因此这里把它们收进一个模块：

| 字段 | 含义 |
|------|------|
| `list_mode` | 当前连续队列的类型（favorites/radar/album/singer/playlist/radio） |
| `player_name` | 当前队列的播放者 |
| `current_playlist_name` | 完整歌单名 |
| Next Queue | 多人 `:next` 累积的待播计数与贡献者 |

写入只经 `adopt()`；守护只读同一份状态（`guard_switch()` / `check_playlist_protection()`），
写与读才不会各说各话。`InfoManager` 仍按 ADR-0004 只做只读门面。
"""

import logging
from typing import Callable, Optional

from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.playback.models import PlaybackMode

# 播放队列的行是「歌名 - 歌手」形式，房间话题取 " - " 之前的部分。
# 这里刻意不做裸连字符切分：歌名里的 "Lo-Fi" 会被吃成 "Lo"。
TOPIC_SEPARATOR = " - "

# 不受歌单守护保护的播放意图：单曲点播。
#
# 守护保护的是「某位普通用户正在放的整张歌单」——收藏、雷达、歌单、歌手、专辑、
# 电台都是连续队列，被中途顶掉就等于把人家没放完的那一叠全扔了。`:play <歌名>`
# 只有一首歌，不该被别人的歌单挡在门外，因此 `guard_switch()` 见到它就放行。
UNPROTECTED_PLAYBACK_MODES = frozenset({PlaybackMode.SONG.value})


def primary_topic(text: Optional[str]) -> str:
    """把播放队列行 / 歌曲文案归一化为房间话题（纯函数）。

    有 " - " 时取之前的部分，否则整段保留。空输入返回空串，调用方据此跳过写话题。

    这个函数是「歌曲文案 → 话题」的唯一规则。QQ 音乐电台副标题（`guess_topic` /
    `daily_topic` / `collection_topic`）用的是另一套裸连字符约定，由
    `QQMusicUIDriver._radio_subtitle_topic` 单独解析，不在此处复用 —— 两类文本
    的约定不同，混用会把其中一类解析错。
    """
    text = (text or "").strip()
    if not text:
        return ""
    if TOPIC_SEPARATOR in text:
        head = text.split(TOPIC_SEPARATOR)[0].strip()
        if head:
            return head
    return text


class PlaylistSession(Singleton):
    """Playlist Context + Next Queue + Playlist Guard 的唯一实现。

    Args:
        handler: SoulHandler，提供 logger 与角色策略配置。
        room_profile: 房名/话题写入端；缺省取 `RoomProfileManager.instance()`。
        online_users: 在线用户查询；缺省取 `PresenceTracker`。
        avatar_usernames: 分身名查询；缺省取 `UserDAO.get_all_avatar_usernames`。
    """

    def __init__(
        self,
        handler=None,
        room_profile=None,
        online_users: Optional[Callable[[], set]] = None,
        avatar_usernames: Optional[Callable[[str], set]] = None,
    ):
        self.handler = handler
        self._logger = handler.logger if handler is not None else None
        self._room_profile = room_profile
        self._online_users = online_users
        self._avatar_usernames = avatar_usernames
        self._list_mode: str = "unknown"
        self._player_name: str = "Joyer"
        self._current_playlist_name: Optional[str] = None
        self._pending_next_count: int = 0
        self._next_queue_contributors: set[str] = set()

    @property
    def logger(self):
        if self._logger is None:
            self._logger = (
                self.handler.logger if self.handler is not None else None
            ) or logging.getLogger("ushareiplay.managers.playlist_session")
        return self._logger

    # ------------------------------------------------------------------
    # Playlist Context
    # ------------------------------------------------------------------
    @property
    def list_mode(self) -> str:
        return self._list_mode

    @list_mode.setter
    def list_mode(self, value: str):
        self._list_mode = value

    @property
    def player_name(self) -> str:
        return self._player_name

    @player_name.setter
    def player_name(self, value: str):
        self._player_name = value
        self.logger.info(f"Player name set to: {value}")

    @property
    def current_playlist_name(self) -> Optional[str]:
        return self._current_playlist_name

    @current_playlist_name.setter
    def current_playlist_name(self, value: str):
        self._current_playlist_name = value
        self.logger.info(f"Playlist name set to: {value}")

    def get_playlist_info(self) -> Optional[dict]:
        """只读歌单视图；没有活跃歌单时返回 None。"""
        if not self._current_playlist_name:
            return None
        return {"type": self._list_mode, "name": self._current_playlist_name}

    # ------------------------------------------------------------------
    # Next Queue
    # ------------------------------------------------------------------
    @property
    def pending_next_count(self) -> int:
        return self._pending_next_count

    @property
    def next_queue_contributors(self) -> set[str]:
        return self._next_queue_contributors

    def record_next(self, requester: str):
        """记录一次成功的 :next：待播数 +1，并加入贡献者。"""
        was_empty = self._pending_next_count == 0
        self._pending_next_count += 1
        self._next_queue_contributors.add(requester)
        if was_empty:
            self.logger.info(f"Next Queue started by: {requester}")

    def consume_track(self) -> None:
        """消费一次曲目切换：待播数 -1（clamp 0），归零时清空贡献者。"""
        if self._pending_next_count == 0:
            return
        self._pending_next_count -= 1
        if self._pending_next_count == 0:
            self._next_queue_contributors.clear()
            self.logger.info("Next Queue emptied")

    def clear_next_queue(self) -> None:
        """清空整个 Next Queue（新歌单已采纳时）。"""
        if self._pending_next_count == 0 and not self._next_queue_contributors:
            return
        self._pending_next_count = 0
        self._next_queue_contributors.clear()
        self.logger.info("Next Queue cleared")

    # ------------------------------------------------------------------
    # Playlist Guard
    # ------------------------------------------------------------------
    @staticmethod
    def _is_single_song(mode: Optional[str]) -> bool:
        """这次请求是不是单点一首歌（纯判据，不读状态、不碰 UI）。

        取不到类型时返回 False：豁免的前提是明确知道「这是一次单点」，说不清
        类型就照旧走角色策略 —— 少问一次不如多问一次。
        """
        return (mode or "").strip().lower() in UNPROTECTED_PLAYBACK_MODES

    def _config(self, config=None):
        if config is not None:
            return config
        return self.handler.config if self.handler is not None else None

    def _online(self) -> set:
        if self._online_users is not None:
            return self._online_users()
        from ushareiplay.state.presence_tracker import PresenceTracker

        return PresenceTracker.instance().get_online_users()

    async def _avatars(self, username: str) -> set:
        if self._avatar_usernames is not None:
            return self._avatar_usernames(username)
        from ushareiplay.dal.user_dao import UserDAO

        return await UserDAO.get_all_avatar_usernames(username)

    async def guard_switch(
        self,
        requester: str,
        incoming_mode: Optional[str] = None,
        config=None,
    ) -> Optional[dict]:
        """歌单守护检查。

        单曲点播不受守护拦：它不采纳歌单上下文，也就没有「顶掉别人队列」这回事；
        但 Timer/Agent 等系统角色的单曲请求是自动打断，不享受这项豁免。

        Returns:
            error dict 表示这次切歌应当被阻断；None 表示放行。
        """
        if self._is_single_song(incoming_mode):
            if not RolePolicy(self._config(config)).is_system_user(requester):
                return None
        return await self.check_playlist_protection(requester, config=config)

    async def check_playlist_protection(
        self, caller_nickname: str, config=None
    ) -> Optional[dict]:
        """当前 Playlist Context 或 Next Queue 是否处于守护状态。

        - 房主、管理员、系统角色播放时无需保护，允许切歌。
        - 普通用户播放且在线时受保护；但房主、管理员可突破保护切歌。
        - Next Queue 由非特权贡献者独立守护，仅贡献者本人/分身与人工操作者可突破。
        """
        role_policy = RolePolicy(self._config(config))

        # 1. 人工操作者（房主、管理员）可突破歌单与 Next Queue 两重守护
        if role_policy.is_human_operator(caller_nickname):
            return None

        # 2. Playlist Context：特权播放者无需保护，本人/分身允许切换，播放者在线则守护
        player_name = self._player_name
        if (
            player_name
            and not role_policy.is_privileged(player_name)
            and caller_nickname != player_name
        ):
            try:
                player_avatars = await self._avatars(player_name)
                is_online = bool(player_avatars & self._online())
            except Exception:
                player_avatars = {player_name}
                is_online = player_name in self._online()
            if caller_nickname not in player_avatars and is_online:
                return {"error": f"{player_name} 正在播放歌单，请等待"}

        # 3. Next Queue：仅非特权贡献者在线时守护，贡献者本人/分身可突破自己的队列
        if self._pending_next_count <= 0:
            return None
        contributors = sorted(
            c for c in self._next_queue_contributors if not role_policy.is_privileged(c)
        )
        online_users = self._online()
        online_contributor = None
        for contributor in contributors:
            contributor_avatars = await self._avatars(contributor)
            if caller_nickname in contributor_avatars:
                return None
            if online_contributor is None and contributor_avatars & online_users:
                online_contributor = contributor

        if online_contributor:
            return {"error": f"{online_contributor} 正在点歌，请等待"}
        return None

    # ------------------------------------------------------------------
    # 采纳（房间同步）
    # ------------------------------------------------------------------
    @property
    def room_profile(self):
        if self._room_profile is None:
            from ushareiplay.managers.room_profile import RoomProfileManager

            self._room_profile = RoomProfileManager.instance()
        return self._room_profile

    def adopt(
        self,
        requester: Optional[str],
        mode: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        playlist: Optional[str] = None,
    ) -> Optional[dict]:
        """把一次已经发生的「歌单切换」同步到房间上下文。

        单曲点播不是歌单切换，因此这里一个字段都不写。写序是接口的一部分：
        状态 → 标题 → 话题。

        Returns:
            第一个错误 dict，成功则为 None。
        """
        if mode == PlaybackMode.SONG.value:
            return None

        # 新的连续歌单接管房间，遗留的临时点歌队列随之作废。
        self.clear_next_queue()

        # 1. 纯状态：与真实播放保持一致，不依赖 Soul 侧 UI 成败
        if requester:
            self.player_name = requester
        self.list_mode = mode
        if playlist is not None:
            self.current_playlist_name = playlist

        # 2. 房间标题
        title_value = (title or "").strip()
        if title_value:
            title_result = self.room_profile.set_title(title_value)
            if isinstance(title_result, dict) and "error" in title_result:
                return title_result

        # 3. 房间话题
        topic_value = primary_topic(topic)
        if topic_value:
            topic_result = self.room_profile.set_topic(topic_value)
            if isinstance(topic_result, dict) and "error" in topic_result:
                return topic_result

        return None
