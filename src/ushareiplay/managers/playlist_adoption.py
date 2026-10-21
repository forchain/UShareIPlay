"""歌单切换后的房间同步 —— 唯一实现。

「房间切歌单之后发生什么」原先散落在六个音乐命令里，是 13 个近似相同的五连写块：

    guard -> player_name = -> list_mode = -> set_title() -> set_topic()

这些块已经漂移：写序不同（album 先话题后标题，其余先标题后话题）、话题切分
有三套规则（不切 / " - " / 裸 "-"）、`list_mode` 直接写在 `QQMusicHandler`
适配器上，而完整的写序只存在于 radio 的一段注释里。

本模块把这套协议收进一个深模块，命令因此收缩为「查询 → 采纳」：

    error = await PlaylistAdoption.instance().guard_switch(requester)
    if error:
        return error
    ...
    error = PlaylistAdoption.instance().adopt(
        requester, mode="radio", title=title, topic=topic, playlist=playlist,
    )

注意 `guard_switch()` 与 `adopt()` 是两件事，不是一个流程的两半：`adopt()` 只负责
「已经决定切歌之后」的同步，因此没有前置守护检查的命令（`:play`、`:fav`）仍然可以
只调用 `adopt()`。

守护只问一件事：**这次要来切的是什么**。

单曲点播不是一次歌单切换（`adopt()` 整条跳过它），因此它既锁不住房间，也不该
被别人的歌单挡在门外 —— 这正是 `UNPROTECTED_PLAYBACK_MODES` 的用途。其余请求
（收藏/雷达/歌单/歌手/专辑/电台，以及说不清类型的）才需要问角色策略：「来切歌的
人有没有这个权限」（见 `InfoManager.check_playlist_protection`）。

历史上守护只问角色策略：`adopt()` 连单曲都写 `player_name`，于是普通房客点一首歌
就能把整个房间的点歌权锁死（2026-10-15 线上，见 #444）；只补上「来切的是单曲」
这一问，另一位房客的单点又会被那句「正在播放歌单」挡回去（2026-10-16 线上，
见 #445）。单曲不再进歌单上下文之后，这两个症状都从根上消失。
"""

from typing import Optional

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
#
# 注意它只是「这次请求」的判据，不是「现在放的」那一侧的状态：单曲不写
# `list_mode`（见 `adopt()`），房间里正在放的永远是一张队列或「未知」。
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


class PlaylistAdoption(Singleton):
    """房间歌单上下文的写入协议：guard_switch() + adopt()。

    持有并写入五个字段，调用方不再各自拼装（单曲 `:play <歌名>` 不在此列 ——
    它不是一次歌单切换，`adopt()` 会整条跳过）：

    | 字段 | 去向 | 时机 |
    |------|------|------|
    | `player_name` | `InfoManager`/`PlaylistState` | adopt 开始 |
    | `list_mode` | `MusicManager`（不再直写 handler） | adopt 开始 |
    | `current_playlist_name` | `InfoManager` | adopt 开始 |
    | 房间标题 | `RoomProfileManager.set_title` | 状态之后 |
    | 房间话题 | `RoomProfileManager.set_topic` | 标题之后 |

    `guard_switch()` 反过来读前两个字段：`list_mode` 回答「现在放的这张队列值不
    值得保护」，`player_name` 交给角色策略回答「谁有资格顶掉它」。写与读都在本模块，
    守护才不会和它要保护的那份状态各说各话。
    """

    def __init__(self):
        # 延迟解析的依赖；测试可直接注入替身（见 ADR-0004 的注入约定）
        self._info = None
        self._room_profile = None
        self._music = None

    @property
    def _info_manager(self):
        if self._info is None:
            from ushareiplay.managers.info_manager import InfoManager
            self._info = InfoManager.instance()
        return self._info

    @property
    def _room_profile_manager(self):
        if self._room_profile is None:
            from ushareiplay.managers.room_profile import RoomProfileManager
            self._room_profile = RoomProfileManager.instance()
        return self._room_profile

    @property
    def _music_manager(self):
        if self._music is None:
            from ushareiplay.managers.music_manager import MusicManager
            self._music = MusicManager.instance()
        return self._music

    @staticmethod
    def _is_single_song(mode: Optional[str]) -> bool:
        """这次请求是不是单点一首歌（纯判据，不读状态、不碰 UI）。

        取不到类型时返回 False：豁免的前提是明确知道「这是一次单点」，说不清
        类型就照旧走角色策略 —— 少问一次不如多问一次。
        """
        return (mode or "").strip().lower() in UNPROTECTED_PLAYBACK_MODES

    async def guard_switch(
        self,
        requester: str,
        incoming_mode: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Optional[dict]:
        """歌单守护检查。

        Args:
            requester: 要切歌的人，交给角色策略。
            incoming_mode: 这次要放的播放类型（`PlaybackMode` 的值）。单曲点播不受
                守护拦：它不采纳歌单上下文，也就没有「顶掉别人队列」这回事；别人
                的歌单也就不该拿它当理由，把一次 `:play <歌名>` 挡在门外
                （2026-10-16 线上：不约儿童 在放歌单，石碘 单点被回以
                「正在播放歌单，请等待」）。None / 说不清类型时照旧走守护。
            config: 角色策略用的配置，原样转交。

        Returns:
            error dict 表示这次切歌应当被阻断；None 表示放行。
        """
        if self._is_single_song(incoming_mode):
            return None
        return await self._info_manager.check_playlist_protection(requester, config=config)

    def adopt(
        self,
        requester: Optional[str],
        mode: str,
        title: Optional[str] = None,
        topic: Optional[str] = None,
        playlist: Optional[str] = None,
    ) -> Optional[dict]:
        """把一次已经发生的「歌单切换」同步到房间上下文。

        单曲点播不是歌单切换，因此这里一个字段都不写（见下方 `mode` 说明）。

        Args:
            requester: 触发切歌的用户名，写入 `player_name`；None/空表示本次不变更播放者
            mode: 播放类型，写入 `list_mode`（favorites/radar/album/singer/playlist/radio）。
                单曲（song）不采纳：房间的歌单上下文描述的是「谁在放一张连续队列」，
                而 `:play <歌名>` 只是插一首歌 —— 正在放的电台/歌单不会因为这首插歌
                就变成点播者的「歌曲」，QQ 音乐放完它还会接着放原来那张队列
                （2026-10-21 线上：电台在放时 `:play 爱情男女`，房间被改写成
                `[song] 猜你喜欢-沉浸刷歌 (by Joyer)`，可电台仍在继续放）。
                这也是 #442「单曲点播禁止修改房间话题」那条规则的补全：话题之外，
                播放者、`list_mode`、歌单名同样不该被一次单点改写。
            title: 房间标题；空则不写（避免用空串覆盖正在生效的标题）
            topic: 房间话题原始文案（播放队列行），经 `primary_topic` 归一化
            playlist: 完整歌单名，写入 `current_playlist_name`；None 表示本次不变更

        Returns:
            第一个错误 dict，成功则为 None。纯状态写入先完成，因此即使 Soul 侧
            标题/话题写入失败，房间对「谁在放、放的是什么类型」的认知仍然正确。

        写序是接口的一部分：状态 → 标题 → 话题。先标题后话题是既有调用点里
        多数派的写序（radio/singer/playlist/fav），也是 radio 注释所记录的次序。
        """
        if mode == PlaybackMode.SONG.value:
            return None

        # 1. 纯状态：与真实播放保持一致，不依赖 Soul 侧 UI 成败
        if requester:
            self._info_manager.player_name = requester
        self._music_manager.list_mode = mode
        if playlist is not None:
            self._info_manager.current_playlist_name = playlist

        # 2. 房间标题
        title_value = (title or "").strip()
        if title_value:
            title_result = self._room_profile_manager.set_title(title_value)
            if isinstance(title_result, dict) and "error" in title_result:
                return title_result

        # 3. 房间话题
        topic_value = primary_topic(topic)
        if topic_value:
            topic_result = self._room_profile_manager.set_topic(topic_value)
            if isinstance(topic_result, dict) and "error" in topic_result:
                return topic_result

        # 标题/话题各自的落地日志由 RoomProfileManager 给出，这里不再重复打日志
        #（也就不必依赖任何一个 logger）。
        return None
