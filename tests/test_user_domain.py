"""用户命名域的纯规则测试：别名链、环检测与等级/热力阈值。

规则只依赖领域对象与注入的查找函数，不碰 Tortoise / Appium。
"""

import pytest

from ushareiplay.modules.shared.errors import DomainError
from ushareiplay.modules.user.domain import (
    AliasCycleError,
    InvalidLevelError,
    User,
    follow_aliases,
    heat_target_level,
    validate_level,
)


def _user(user_id, canonical_user_id=None):
    return User(id=user_id, username=f"u{user_id}", canonical_user_id=canonical_user_id)


def _directory(*users):
    return {user.id: user for user in users}


def test_follow_aliases_returns_the_canonical_root():
    users = _directory(
        _user(1, canonical_user_id=2),
        _user(2, canonical_user_id=3),
        _user(3),
    )

    assert follow_aliases(users[1], users.get) is users[3]


def test_follow_aliases_returns_the_start_when_a_link_is_broken():
    start = _user(1, canonical_user_id=99)

    assert follow_aliases(start, _directory().get) is start


def test_follow_aliases_rejects_a_self_reference():
    loop = _user(1, canonical_user_id=1)

    with pytest.raises(AliasCycleError):
        follow_aliases(loop, _directory(loop).get)


def test_follow_aliases_rejects_a_cycle_back_to_the_start():
    a = _user(1, canonical_user_id=2)
    b = _user(2, canonical_user_id=1)

    with pytest.raises(AliasCycleError):
        follow_aliases(a, _directory(a, b).get)


def test_alias_cycle_error_is_a_domain_error():
    assert issubclass(AliasCycleError, DomainError)


@pytest.mark.parametrize("level", [0, 1, 5, 9])
def test_validate_level_accepts_zero_to_nine(level):
    assert validate_level(level) == level


@pytest.mark.parametrize("level", [-1, 10])
def test_validate_level_rejects_out_of_range(level):
    with pytest.raises(InvalidLevelError):
        validate_level(level)


@pytest.mark.parametrize(
    ("heat", "expected"),
    [
        (0, 5),
        (10_000, 5),
        (10_001, 6),
        (100_000, 6),
        (100_001, 7),
        (1_000_000, 7),
        (1_000_001, 8),
    ],
)
def test_heat_target_level_matches_existing_thresholds(heat, expected):
    assert heat_target_level(heat) == expected
