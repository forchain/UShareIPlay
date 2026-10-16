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

守护本身问三个问题，缺一不可：

1. 「现在放的这张队列值不值得保护」（单曲点播不保护，见
   `UNPROTECTED_PLAYBACK_MODES`）；
2. 「要来切的这一手是不是单曲」（单曲请求同样不受保护 —— 它不该反过来被
   别人的歌单挡在门外）；
3. 前两问都成立时，才问「来切歌的人有没有这个权限」（角色策略，见
   `InfoManager.check_playlist_protection`）。

只问第 3 问的话，一位普通房客点一首歌就能把整个房间的点歌权锁死；第 2 问缺了
的话，另一位房客的单点又会被那句「正在播放歌单」挡回去 —— 单曲在守护眼里两头都
不该是理由。
"""

from typing import Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.playback.models import PlaybackMode

# 播放队列的行是「歌名 - 歌手」形式，房间话题取 " - " 之前的部分。
# 这里刻意不做裸连字符切分：歌名里的 "Lo-Fi" 会被吃成 "Lo"。
TOPIC_SEPARATOR = " - "

# 不受歌单守护保护的播放类型：单曲点播。
#
# 守护保护的是「某位普通用户正在放的整张歌单」——收藏、雷达、歌单、歌手、专辑、
# 电台都是连续队列，被中途顶掉就等于把人家没放完的那一叠全扔了。`:play <歌名>`
# 只有一首歌，放完就该把切歌权交还给房间，因此它既不该被守护拦住，也不该反过来
# 用一次点播锁住整个房间：这个类型在 `guard_switch()` 里两头都用得上——作为
# 「现在放的」时不产生保护，作为「要来切的」时不受保护。
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

    持有并写入五个字段，调用方不再各自拼装：

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
    def _is_protected_mode(mode: Optional[str]) -> bool:
        """某个播放类型值不值得守护（纯判据，不读状态、不碰 UI）。

        单曲不受保护，见 `UNPROTECTED_PLAYBACK_MODES`。取不到类型时按受保护处理
        —— 守护是房间既有的默认规则，豁免的前提是明确知道「这是单曲」。
        """
        return (mode or "").strip().lower() not in UNPROTECTED_PLAYBACK_MODES

    def _current_playback_is_protected(self) -> bool:
        """房间里正在放的东西值不值得守护（只读状态，不碰 UI）。

        判据是 `adopt()` 记下的播放类型，不是「有没有人在放」：一次单曲点播同样
        会把 `player_name` 写成点播者，只看播放者就会把「他点了首歌」误当成
        「他在放歌单」，从此谁都点不动歌。

        生产路径上 `adopt()` 总是与 `player_name` 同批写入 `list_mode`，因此
        「取不到类型」的兜底只在依赖尚未装配时生效。
        """
        return self._is_protected_mode(getattr(self._music_manager, "list_mode", None))

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
                守护拦：既然「单曲不值得被保护」，别人的歌单也就不该拿它当理由，
                把一次 `:play <歌名>` 挡在门外（2026-10-16 线上：不约儿童 在放歌单，
                石碘 单点被回以「正在播放歌单，请等待」）。None / 说不清类型时照旧
                走守护 —— 少问一次不如多问一次。
            config: 角色策略用的配置，原样转交。

        Returns:
            error dict 表示这次切歌应当被阻断；None 表示放行。
        """
        if not self._current_playback_is_protected():
            return None
        if not self._is_protected_mode(incoming_mode):
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
        """把一次已经发生的播放切换同步到房间上下文。

        Args:
            requester: 触发切歌的用户名，写入 `player_name`；None/空表示本次不变更播放者
            mode: 播放类型，写入 `list_mode`（favorites/radar/album/singer/playlist/radio/song）
            title: 房间标题；空则不写（避免用空串覆盖正在生效的标题）
            topic: 房间话题原始文案（播放队列行或歌曲名），经 `primary_topic` 归一化；单曲模式（song）不修改话题
            playlist: 完整歌单名，写入 `current_playlist_name`；None 表示本次不变更

        Returns:
            第一个错误 dict，成功则为 None。纯状态写入先完成，因此即使 Soul 侧
            标题/话题写入失败，房间对「谁在放、放的是什么类型」的认知仍然正确。

        写序是接口的一部分：状态 → 标题 → 话题。先标题后话题是既有调用点里
        多数派的写序（radio/singer/playlist/fav），也是 radio 注释所记录的次序。
        """
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

        # 3. 房间话题（单曲播放不修改房间话题）
        if mode != "song":
            topic_value = primary_topic(topic)
            if topic_value:
                topic_result = self._room_profile_manager.set_topic(topic_value)
                if isinstance(topic_result, dict) and "error" in topic_result:
                    return topic_result

        # 标题/话题各自的落地日志由 RoomProfileManager 给出，这里不再重复打日志
        #（也就不必依赖任何一个 logger）。
        return None
