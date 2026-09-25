"""房间横幅文案清洗 + PendingWrite 内核。

两者都是候选 7 抽出来的共用机件：前者原先在房间名与话题里各写一份相同的
切分链，后者是三个 manager 各自的冷却/pending/重试状态机。
"""

from datetime import datetime, timedelta

import pytest

from ushareiplay.helpers.room_banner import (
    TITLE_MAX_LENGTH,
    TOPIC_MAX_LENGTH,
    clean_banner_text,
)
from ushareiplay.managers.pending_write import PendingWrite


class TestCleanBannerText:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("夜曲", "夜曲"),
            ("夜曲｜周杰伦", "夜曲"),
            ("夜曲|周杰伦", "夜曲"),
            ("夜曲丨周杰伦", "夜曲"),
            ("夜曲(演唱会版)", "夜曲"),
            ("夜曲（演唱会版）", "夜曲"),
            ("  晚安 | 早点睡  ", "晚安"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_truncates_at_the_first_decoration(self, raw, expected):
        assert clean_banner_text(raw, TOPIC_MAX_LENGTH) == expected

    def test_length_limit_is_per_caller(self):
        long_text = "一二三四五六七八九十十一十二十三"
        assert clean_banner_text(long_text, TITLE_MAX_LENGTH) == long_text[:TITLE_MAX_LENGTH]
        assert clean_banner_text(long_text, TOPIC_MAX_LENGTH) == long_text[:TOPIC_MAX_LENGTH]
        assert len(clean_banner_text(long_text, TITLE_MAX_LENGTH)) == 12
        assert len(clean_banner_text(long_text, TOPIC_MAX_LENGTH)) == 15


@pytest.fixture
def cooldown_managers():
    """三个共用冷却内核的 manager（房间名 / 公告 / 话题）。"""
    from ushareiplay.managers.notice_manager import NoticeManager
    from ushareiplay.managers.room_name_manager import RoomNameManager
    from ushareiplay.managers.topic_manager import TopicManager

    for cls in (RoomNameManager, NoticeManager, TopicManager):
        cls.reset_instance()
    managers = (RoomNameManager.initialize(), NoticeManager.initialize(), TopicManager.initialize())
    yield managers
    for cls in (RoomNameManager, NoticeManager, TopicManager):
        cls.reset_instance()


class TestPendingWrite:
    def test_first_write_is_allowed_immediately(self):
        write = PendingWrite(cooldown_minutes=10)
        assert write.can_apply_now() is True
        assert write.remaining_minutes() == 0

    def test_cooldown_starts_after_the_first_attempt(self):
        write = PendingWrite(cooldown_minutes=10)
        write.mark_attempted()
        assert write.can_apply_now() is False
        # 刚尝试完：剩余略少于整个冷却时长（int() 向下截断，与原先三份实现一致）
        assert write.remaining_minutes() == 9

    def test_cooldown_expires(self):
        write = PendingWrite(cooldown_minutes=10)
        write.mark_attempted(now=datetime.now() - timedelta(minutes=11))
        assert write.can_apply_now() is True
        assert write.remaining_minutes() == 0

    def test_remaining_minutes_counts_down(self):
        write = PendingWrite(cooldown_minutes=10)
        write.mark_attempted(now=datetime.now() - timedelta(minutes=2, seconds=30))
        assert write.remaining_minutes() == 7

    def test_pending_is_kept_until_cleared(self):
        write = PendingWrite(cooldown_minutes=5)
        assert write.has_pending is False

        write.submit("话题A")
        assert write.pending == "话题A"
        assert write.has_pending is True

        # 尝试失败：时钟推进，但待写入值保留，等下个周期
        write.mark_attempted()
        assert write.pending == "话题A"

        # 尝试成功：清空
        write.clear()
        assert write.pending is None
        assert write.has_pending is False

    def test_submit_overwrites_the_previous_pending_value(self):
        write = PendingWrite(cooldown_minutes=5)
        write.submit("第一个")
        write.submit("第二个")
        assert write.pending == "第二个"

    def test_cooldown_is_a_parameter_not_a_convention(self, cooldown_managers):
        """三个 manager 的冷却时长分别是 10 / 15 / 5 分钟 —— 是参数，不是三套语义。"""
        room_name, notice, topic = cooldown_managers
        assert room_name.cooldown_minutes == 10
        assert notice.cooldown_minutes == 15
        assert topic.cooldown_minutes == 5

    def test_managers_share_one_implementation_of_the_clock(self, cooldown_managers):
        """三个 manager 的时钟语义一致：未尝试即可写，尝试后进入冷却。"""
        for manager in cooldown_managers:
            assert manager.last_update_time is None
            assert manager.can_update_now() is True
            assert manager.get_remaining_cooldown_minutes() == 0

            manager.last_update_time = datetime.now()
            assert manager.can_update_now() is False
            assert manager.get_remaining_cooldown_minutes() >= manager.cooldown_minutes - 1
