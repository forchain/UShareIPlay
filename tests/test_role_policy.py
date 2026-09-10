import pytest
from ushareiplay.core.roles import RolePolicy


def test_default_roles_when_empty_config():
    policy = RolePolicy({})
    assert policy.is_room_owner("Joyer") is True
    assert policy.is_room_owner("Console") is True
    assert policy.is_room_owner("console") is True
    assert policy.is_admin("Outlier") is True
    assert policy.is_admin("Chainer") is True
    assert policy.is_admin("outlier") is True
    assert policy.is_admin("Joyer") is True
    assert policy.is_admin("Console") is True
    assert policy.is_system_user("Timer") is True
    assert policy.is_system_user("Agent") is True
    assert policy.is_system_user("timer") is True
    assert policy.is_human_operator("Joyer") is True
    assert policy.is_human_operator("Outlier") is True
    assert policy.is_human_operator("Console") is True
    assert policy.is_human_operator("Timer") is False
    assert policy.is_human_operator("Agent") is False
    assert policy.is_human_operator("Alice") is False
    assert policy.is_system_user("Alice") is False


def test_custom_roles_from_nested_soul_config():
    config = {
        "soul": {
            "room_owner": "Alice",
            "admin_users": ["Bob", "Charlie"],
            "system_users": ["Bot1", "Bot2"],
        }
    }
    policy = RolePolicy(config)
    assert policy.is_room_owner("Alice") is True
    assert policy.is_room_owner("Console") is True
    assert policy.is_admin("Bob") is True
    assert policy.is_admin("Charlie") is True
    assert policy.is_admin("Alice") is True
    assert policy.is_admin("Outlier") is False
    assert policy.is_system_user("Bot1") is True
    assert policy.is_system_user("Bot2") is True
    assert policy.is_system_user("Timer") is False
    assert policy.is_human_operator("Bob") is True
    assert policy.is_human_operator("Bot1") is False


def test_custom_roles_from_root_config():
    config = {
        "room_owner": "Dave",
        "admin_users": ["Eve"],
        "system_users": ["Cron"],
    }
    policy = RolePolicy(config)
    assert policy.is_room_owner("Dave") is True
    assert policy.is_room_owner("Console") is True
    assert policy.is_admin("Eve") is True
    assert policy.is_system_user("Cron") is True
    assert policy.is_human_operator("Eve") is True
    assert policy.is_human_operator("Cron") is False


def test_explicit_empty_admin_and_system_users():
    config = {
        "soul": {
            "room_owner": "Dave",
            "admin_users": [],
            "system_users": [],
        }
    }
    policy = RolePolicy(config)
    assert policy.is_room_owner("Dave") is True
    assert policy.is_room_owner("Console") is True
    # Outlier and Chainer should NOT be admins when admin_users is explicitly empty
    assert policy.is_admin("Outlier") is False
    assert policy.is_admin("Chainer") is False
    # Timer and Agent should NOT be system users when system_users is explicitly empty
    assert policy.is_system_user("Timer") is False
    assert policy.is_system_user("Agent") is False
    # Only room owner and Console are admins
    assert policy.is_admin("Dave") is True
    assert policy.is_admin("Console") is True
    assert policy.is_privileged("Dave") is True
    assert policy.is_privileged("Outlier") is False

