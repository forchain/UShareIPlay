"""PlaylistAdoption 的接口级测试。

这里替代了原先六份 mock 链：房间同步现在只有一个实现，因此也只需要一套断言。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ushareiplay.managers.playlist_adoption import PlaylistAdoption, primary_topic


class _Info:
    def __init__(self):
        self.player_name = None
        self.current_playlist_name = None


class _RoomName:
    def __init__(self):
        self.titles = []
        self.result = {}

    def set_next_title(self, title):
        self.titles.append(title)
        return self.result


class _Topic:
    def __init__(self):
        self.topics = []
        self.result = {}

    def change_topic(self, topic):
        self.topics.append(topic)
        return self.result


class _Music:
    def __init__(self):
        self.list_mode = None


@pytest.fixture
def adoption():
    """把 PlaylistAdoption 的三个协作者替换为替身（模块级注入，见 ADR-0004）。"""
    module = PlaylistAdoption.instance()
    module._info = _Info()
    module._room_name = _RoomName()
    module._topic = _Topic()
    module._music = _Music()
    return module


# --------------------------------------------------------------------------
# primary_topic：歌曲文案 → 房间话题的唯一规则
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("晴天 - 周杰伦", "晴天"),          # 播放队列行：取歌名
        ("Lo-Fi 歌 - 某人", "Lo-Fi 歌"),     # " - " 之前的部分原样保留，歌名里的连字符不被吃
        ("Lo-Fi 歌", "Lo-Fi 歌"),            # 没有 " - " 时整段保留
        ("晴天", "晴天"),
        ("  晴天 - 周杰伦  ", "晴天"),
        ("", ""),
        (None, ""),
        # 分隔符切出来是空 -> 说明格式不是「歌名 - 歌手」，此时保留整段而不是丢内容
        (" - 只有分隔符", "- 只有分隔符"),
    ],
)
def test_primary_topic_takes_the_segment_before_the_song_line_separator(raw, expected):
    assert primary_topic(raw) == expected


# --------------------------------------------------------------------------
# adopt：五字段写入
# --------------------------------------------------------------------------

def test_adopt_writes_all_five_fields(adoption):
    assert adoption.adopt(
        requester="张三", mode="radio", title="O Radio",
        topic="晴天 - 周杰伦", playlist="O Radio",
    ) is None

    assert adoption._info.player_name == "张三"
    assert adoption._music.list_mode == "radio"
    assert adoption._info.current_playlist_name == "O Radio"
    assert adoption._room_name.titles == ["O Radio"]
    assert adoption._topic.topics == ["晴天"]


def test_adopt_without_requester_leaves_the_current_player_untouched(adoption):
    adoption._info.player_name = "原播放者"
    adoption.adopt(requester=None, mode="album", title="范特西")
    assert adoption._info.player_name == "原播放者"


def test_adopt_leaves_playlist_name_untouched_when_not_given(adoption):
    adoption._info.current_playlist_name = "上一份歌单"
    adoption.adopt(requester="张三", mode="radar", title="O Radio")
    assert adoption._info.current_playlist_name == "上一份歌单"


def test_adopt_skips_empty_title_and_topic(adoption):
    """空标题/空话题不得覆盖正在生效的房间名 —— 也不得把 None 传给 change_topic。"""
    adoption.adopt(requester="张三", mode="album", title="", topic=None)
    assert adoption._room_name.titles == []
    assert adoption._topic.topics == []


def test_adopt_writes_pure_state_before_soul_side_writes(adoption):
    """写序是接口的一部分：Soul 侧写入失败时，房间对「谁在放、什么类型」的认知仍然正确。"""
    adoption._room_name.result = {"error": "Cannot switch to Soul app"}

    error = adoption.adopt(requester="张三", mode="radio", title="O Radio", playlist="O Radio")

    assert error == {"error": "Cannot switch to Soul app"}
    assert adoption._info.player_name == "张三"
    assert adoption._music.list_mode == "radio"
    assert adoption._info.current_playlist_name == "O Radio"
    assert adoption._topic.topics == []  # 标题失败后不再继续写话题


def test_adopt_returns_topic_error_after_title_succeeded(adoption):
    adoption._topic.result = {"error": "Failed to switch to Soul app"}

    error = adoption.adopt(requester="张三", mode="radio", title="O Radio", topic="晴天")

    assert error == {"error": "Failed to switch to Soul app"}
    assert adoption._room_name.titles == ["O Radio"]
    assert adoption._topic.topics == ["晴天"]


class _Missing:
    """没有 set_next_title 的替身，用来确认非 error 返回不被误判。"""

    def set_next_title(self, _title):
        return {"skipped": True, "reason": "guest_room"}


def test_adopt_treats_non_error_result_as_success(adoption):
    """房间名为游客房跳过时返回 {'skipped': ...}，不是错误。"""
    adoption._room_name = _Missing()
    assert adoption.adopt(requester="张三", mode="radio", title="O Radio") is None


# --------------------------------------------------------------------------
# guard_switch：守护检查的转发
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_switch_forwards_to_the_protection_check(adoption):
    adoption._info = MagicMock()
    adoption._info.check_playlist_protection = AsyncMock(return_value={"error": "被守护"})

    result = await adoption.guard_switch("Timer", config={"soul": {}})

    adoption._info.check_playlist_protection.assert_awaited_once_with(
        "Timer", config={"soul": {}}
    )
    assert result == {"error": "被守护"}
