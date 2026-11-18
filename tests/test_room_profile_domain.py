"""房间档案的纯领域规则：房名校验、主题、推荐状态与冷却异常。

这些规则不碰 UI、不读配置、不碰房间状态；用例层只负责把它们接到端口和
既有返回 dict 上。ADR-0001 的 `{theme}｜{title}` 不变量与 ADR-0011 的
「字段预算 / 抽屉表面」两问都从这里取语义。
"""

from datetime import datetime, timedelta

import pytest

from ushareiplay.modules.room.domain import (
    FULLWIDTH_SEPARATOR,
    InvalidRoomName,
    ProfileCooldown,
    ProfileDraftStore,
    clean_banner_text,
    compose_room_name,
    parse_room_title_text,
    recommendation_status_from_text,
    validate_theme,
)


class TestRoomName:
    def test_theme_is_limited_to_two_characters(self):
        assert validate_theme("听歌") == "听歌"
        assert validate_theme("听") == "听"

    def test_theme_length_is_checked_before_stripping(self):
        """既有的长度判定在 strip 之前，带空格同样超限 —— 逐字保留。"""
        with pytest.raises(InvalidRoomName) as caught:
            validate_theme("  听歌  ")
        assert str(caught.value) == "主题最多两个字符"

    def test_theme_must_not_be_blank(self):
        with pytest.raises(InvalidRoomName) as caught:
            validate_theme("")
        assert str(caught.value) == "主题不能为空"

    def test_room_name_is_the_theme_and_title_joined_by_the_fullwidth_bar(self):
        assert FULLWIDTH_SEPARATOR == "｜"
        assert compose_room_name("三福", "Lofi Girl") == "三福｜Lofi Girl"
        assert compose_room_name("听歌", None) == "听歌｜"

    def test_parsing_splits_only_the_first_fullwidth_bar(self):
        assert parse_room_title_text("三福｜Lofi Girl") == ("三福", "Lofi Girl")
        assert parse_room_title_text("三福｜Lofi｜Girl") == ("三福", "Lofi｜Girl")
        assert parse_room_title_text("没有分隔符") is None

    def test_banner_text_is_truncated_at_the_first_decoration(self):
        assert clean_banner_text("  晚安 | 早点睡  ", 15) == "晚安"
        assert clean_banner_text("一二三四五六七八九十十一十二十三", 12) == "一二三四五六七八九十十一"


class TestProfileCooldown:
    def test_a_free_field_allows_a_write(self):
        assert ProfileDraftStore().require_can_start("topic") is None

    def test_a_spent_budget_raises_the_cooldown_exception_with_the_remaining_minutes(self):
        drafts = ProfileDraftStore()
        drafts.mark_attempted("notice", now=datetime.now() - timedelta(minutes=2))

        with pytest.raises(ProfileCooldown) as caught:
            drafts.require_can_start("notice")

        assert caught.value.field == "notice"
        assert caught.value.remaining_minutes == 12

    def test_the_surface_quiet_period_also_counts_as_cooldown(self):
        drafts = ProfileDraftStore()
        drafts.mark_attempted("topic", now=datetime.now() - timedelta(seconds=10))

        with pytest.raises(ProfileCooldown) as caught:
            drafts.require_can_start("notice")

        assert caught.value.field == "notice"
        assert caught.value.remaining_minutes == 1  # 表面 60 秒向上取整


class TestRecommendationStatus:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("所有人", True),
            ("关闭推荐分发", False),
            ("未知文案", None),
            ("", None),
        ],
    )
    def test_status_text_maps_to_the_switch_state(self, text, expected):
        assert recommendation_status_from_text(text) is expected
