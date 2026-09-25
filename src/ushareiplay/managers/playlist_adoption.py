"""歌单切换后的房间同步 —— 唯一实现。

「房间切歌单之后发生什么」原先散落在六个音乐命令里，是 13 个近似相同的五连写块：

    guard -> player_name = -> list_mode = -> set_next_title() -> change_topic()

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
"""

from typing import Optional

from ushareiplay.core.singleton import Singleton

# 播放队列的行是「歌名 - 歌手」形式，房间话题取 " - " 之前的部分。
# 这里刻意不做裸连字符切分：歌名里的 "Lo-Fi" 会被吃成 "Lo"。
TOPIC_SEPARATOR = " - "


def primary_topic(text: Optional[str]) -> str:
    """把播放队列行 / 歌曲文案归一化为房间话题（纯函数）。

    有 " - " 时取之前的部分，否则整段保留。空输入返回空串，调用方据此跳过写话题。

    这个函数是「歌曲文案 → 话题」的唯一规则。QQ 音乐电台副标题（`guess_topic` /
    `daily_topic` / `collection_topic`）用的是另一套裸连字符约定，由
    `RadioCommand._extract_primary_topic` 单独解析，不在此处复用 —— 两类文本
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
    | 房间标题 | `RoomNameManager.set_next_title` | 状态之后 |
    | 房间话题 | `TopicManager.change_topic` | 标题之后 |
    """

    def __init__(self):
        # 延迟解析的依赖；测试可直接注入替身（见 ADR-0004 的注入约定）
        self._info = None
        self._room_name = None
        self._topic = None
        self._music = None

    @property
    def _info_manager(self):
        if self._info is None:
            from ushareiplay.managers.info_manager import InfoManager
            self._info = InfoManager.instance()
        return self._info

    @property
    def _room_name_manager(self):
        if self._room_name is None:
            from ushareiplay.managers.room_name_manager import RoomNameManager
            self._room_name = RoomNameManager.instance()
        return self._room_name

    @property
    def _topic_manager(self):
        if self._topic is None:
            from ushareiplay.managers.topic_manager import TopicManager
            self._topic = TopicManager.instance()
        return self._topic

    @property
    def _music_manager(self):
        if self._music is None:
            from ushareiplay.managers.music_manager import MusicManager
            self._music = MusicManager.instance()
        return self._music

    async def guard_switch(self, requester: str, config: Optional[dict] = None) -> Optional[dict]:
        """歌单守护检查。

        Returns:
            error dict 表示这次切歌应当被阻断；None 表示放行。
        """
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
            mode: 播放类型，写入 `list_mode`（favorites/radar/album/singer/playlist/radio）
            title: 房间标题；空则不写（避免用空串覆盖正在生效的标题）
            topic: 房间话题原始文案（播放队列行或歌曲名），经 `primary_topic` 归一化
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
            title_result = self._room_name_manager.set_next_title(title_value)
            if isinstance(title_result, dict) and "error" in title_result:
                return title_result

        # 3. 房间话题
        topic_value = primary_topic(topic)
        if topic_value:
            topic_result = self._topic_manager.change_topic(topic_value)
            if isinstance(topic_result, dict) and "error" in topic_result:
                return topic_result

        # 标题/话题各自的落地日志由 RoomNameManager / TopicManager 给出，
        # 这里不再重复打日志（也就不必依赖任何一个 logger）。
        return None
