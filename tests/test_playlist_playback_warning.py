"""点完「播放全部」却读不回队列时，歌单播放仍然算成功（#434）。

迁移前这段逻辑在 `PlaylistCommand.play_playlist` 里，现在归
`QQMusicUIDriver._play_playlist` —— 因此本文件改为在**驱动**这一层断言：
「播放全部」点过一次、读队列失败记一条 warning、回复退回歌单名，而 UI 上观察到
的歌单名/房名/话题照原样交给引擎。

房间状态的落地（`list_mode`/`current_playlist_name`/房名/话题）由
`tests/test_playlist_adoption.py` 在模块接口层覆盖，`tests/test_playlist_command_migration.py`
覆盖引擎把它接起来的那一段；这里刻意不再重复断言那些写入。
"""

from types import SimpleNamespace

from ushareiplay.managers.playback.models import PlaybackMode, PlaybackRequest
from ushareiplay.managers.playback.qq_music_ui_driver import (
    PLAY_ALL_KEYS,
    PLAYLIST_RESULT_KEYS,
    QQMusicUIDriver,
)


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))


class _Element:
    def __init__(self, text=""):
        self.text = text
        self.clicks = 0

    def click(self):
        self.clicks += 1


class _QueueUnreadableHandler:
    """唯一故障点：`get_playlist_info()` 读不回队列。

    其余旋钮都指向成功路径，因此断言失败时能一眼看出是「读队列」这一处坏了，
    而不是别的关节。
    """

    def __init__(self, playlist_name="学习|英语", playlist_info=None):
        self.logger = _Logger()
        self.playlist_info = (
            playlist_info
            if playlist_info is not None
            else {"error": "No songs found in playlist"}
        )
        self.play_button = _Element("play")
        self.result_card = _Element(playlist_name)
        self.queue_reads = 0
        self._element_finder = SimpleNamespace(
            wait_for_any_element=self._wait_any,
            try_find_element=lambda key: None,
        )

    @property
    def element_finder(self):
        return self._element_finder

    def query_music(self, query):
        return "search_box"

    def _wait_any(self, keys):
        if keys == PLAYLIST_RESULT_KEYS:
            return "playlist_result", self.result_card
        if keys == PLAY_ALL_KEYS:
            return "play_all", self.play_button
        raise AssertionError(f"unexpected keys: {keys}")

    def get_playlist_info(self):
        self.queue_reads += 1
        return self.playlist_info


def _playlist_request(query):
    """歌单模式的请求。刻意直接构造：`playlist` 是数据类的字段，不是构造器名。"""
    return PlaybackRequest(mode=PlaybackMode.PLAYLIST, query=query, requester="小明")


def _play(handler):
    """驱动跑一次歌单编排；分类 tab 用替身顶掉，避免真的去切 UI。"""
    from ushareiplay.managers.music_manager import MusicManager

    MusicManager.initialize().select_tab = lambda name, **kwargs: True
    return QQMusicUIDriver(handler).start_playback(_playlist_request("study"))


def test_playlist_info_error_warns_and_falls_back_to_the_playlist_name(
    initialized_test_singletons,
):
    handler = _QueueUnreadableHandler()

    outcome = _play(handler)

    assert outcome.ok is True, "歌已经放起来了，读队列失败不该报成播放失败"
    assert handler.play_button.clicks == 1
    assert handler.queue_reads == 1
    assert any(
        level == "warning" and "No songs found in playlist" in message
        for level, message in handler.logger.messages
    )


def test_the_parsed_room_state_survives_a_queue_that_cannot_be_read(
    initialized_test_singletons,
):
    """读不回队列时，引擎仍然拿得到 UI 上真实看到的歌单名/房名/话题。"""
    handler = _QueueUnreadableHandler(playlist_name="学习|英语")

    outcome = _play(handler)

    assert (outcome.title, outcome.topic, outcome.playlist) == ("学习", "英语", "学习|英语")


def test_the_reply_falls_back_to_the_playlist_name_verbatim(
    initialized_test_singletons,
):
    """`:playlist` 的回复模板是纯 `{playlist}`：读不到队列就退回歌单名，而不是空串。"""
    handler = _QueueUnreadableHandler(playlist_name="学习|英语")

    outcome = _play(handler)

    assert outcome.extra["playlist"] == "学习|英语"


def test_a_readable_queue_is_what_the_reply_carries(initialized_test_singletons):
    """对照组：队列读得到时，回复带的是队列本身，而不是歌单名。"""
    handler = _QueueUnreadableHandler(
        playlist_info={"playlist": "似是故人来 - 梅艳芳\n如风 - 王菲"}
    )

    outcome = _play(handler)

    assert outcome.extra["playlist"] == "似是故人来 - 梅艳芳\n如风 - 王菲"
