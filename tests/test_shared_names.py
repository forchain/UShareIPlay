"""共享内核的命名域值对象与领域异常基类。

归一化口径沿用现有 InfoManager / UserManager 行为：Soul UI 与 DB 里的名字按
去除首尾空白后逐字比较，大小写敏感（`PresenceTracker.is_user_online` /
`UserDAO.is_same_identity`）；空名字保持为空，不额外拒绝。
"""

import pytest

from ushareiplay.modules.shared.errors import DomainError
from ushareiplay.modules.shared.names import CanonicalName, VisibleName


def test_visible_name_strips_surrounding_whitespace():
    assert VisibleName("  Alice\t").value == "Alice"
    assert VisibleName("Alice").value == "Alice"


def test_visible_name_is_case_sensitive():
    assert VisibleName("Alice") != VisibleName("alice")
    assert VisibleName("Alice").value == "Alice"


def test_visible_name_allows_an_empty_name_like_info_manager():
    assert VisibleName("   ").value == ""
    assert not VisibleName("")


def test_canonical_name_strips_surrounding_whitespace():
    assert CanonicalName("\nOutlier  ").value == "Outlier"


def test_names_from_the_two_domains_are_never_equal():
    assert VisibleName("Alice") != CanonicalName("Alice")


def test_names_are_hashable_and_render_as_their_value():
    assert {VisibleName("Alice"), VisibleName(" Alice ")} == {VisibleName("Alice")}
    assert str(VisibleName("Alice")) == "Alice"
    assert repr(VisibleName("Alice")) == "VisibleName(value='Alice')"


def test_domain_error_is_the_shared_base_error():
    class SeatOccupied(DomainError):
        pass

    assert issubclass(SeatOccupied, DomainError)
    with pytest.raises(DomainError):
        raise SeatOccupied("座位已被占用")
