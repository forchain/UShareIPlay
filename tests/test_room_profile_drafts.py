"""草稿库：只剩一个排队入口，且不再藏着第二份房名合成。

两处「看起来多余、实际是陷阱」的死代码在这一票里被删掉：

- `compose_room_title()` —— 零调用点的副本，而且它是**错的**那一份：没有排队
  主题时它拼出 `None｜标题`。真正被 `RoomProfileManager` 接线使用的那一份
  （`manager.py`）会用当前主题兜底。留着它，下一个读者就可能把 `None｜` 写进
  一个真实房间。
- `submit()` —— 纯粹转发给 `set_pending()` 的中间人。排队只有一条路可走，
  两条同义入口只会让人猜哪条才是被推荐的那条。

`set_pending()` 本身的行为测试在 `test_room_profile_manager.py`（草稿库那一节），
本文件只**钉住**这两样东西不再长回来，以及真正接线的那份房名合成不写 `None｜`。
"""

import pytest

from ushareiplay.managers.room_profile.drafts import FIELDS, ProfileDraftStore
from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.state.room_state import RoomState


@pytest.fixture(autouse=True)
def reset_singletons():
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()
    yield
    for cls in (RoomProfileManager, RoomState):
        cls.reset_instance()


# --------------------------------------------------------------------------
# 死代码不得长回来
# --------------------------------------------------------------------------


def test_the_draft_store_has_no_duplicate_submit_alias():
    """`submit()` 已被 `set_pending()` 取代，排队只有一条路可走。"""
    assert not hasattr(ProfileDraftStore, "submit")


def test_the_draft_store_does_not_duplicate_the_room_title_composer():
    """`None｜标题` 的那一份必须消失，否则迟早有人调用错的那一份。"""
    assert not hasattr(ProfileDraftStore, "compose_room_title")


# --------------------------------------------------------------------------
# 唯一一份房名合成：接线在 manager 上，且从不写出 None｜
# --------------------------------------------------------------------------


def test_the_room_title_is_composed_by_the_manager_which_never_writes_none():
    profile = RoomProfileManager.initialize()
    profile.drafts.set_pending("title", "晚安")

    composed = profile.compose_room_title()

    assert composed == f"{profile.current_theme}｜晚安"
    assert "None" not in composed, "冷启动后第一次改标题不得写成 None｜标题"


@pytest.mark.parametrize("field", FIELDS)
def test_every_declared_field_keeps_its_own_cooldown_budget(field):
    """三个字段互不消耗预算 —— 写话题不会让公告一起进冷却。"""
    drafts = ProfileDraftStore()
    drafts.mark_attempted(field)

    for other in FIELDS:
        if other != field:
            assert drafts.can_apply_now(other) is True
