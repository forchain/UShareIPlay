"""soul 段读取走段视图：段参数与 UI 选择器各有各的入口。

段参数（`party_restart_minutes`、`default_party_id` 之类）走 `.value` /
`.require`；UI 选择器只走 `.element` / `.maybe_element`，调用方不再自己
去翻 `soul.elements` 这张表。
"""

import pytest

from ushareiplay.core.config_view import (
    ConfigSectionView,
    ConfigView,
    Locator,
    MissingConfigKey,
    MissingElementKey,
)


def _soul_data():
    return {
        "room_owner": "Joyer",
        "party_restart_minutes": 60,
        "default_party_id": "FM15321640",
        "elements": {
            "message_content": (
                "//android.widget.TextView"
                "[@resource-id='cn.soulapp.android:id/tvContent']"
            ),
            "message_list": "cn.soulapp.android:id/rvMessage",
            "button_send": "cn.soulapp.android:id/btnSend",
        },
        "post_party_create": {"enabled": True, "commands": [":skip"]},
    }


def _soul_section():
    return ConfigSectionView("soul", _soul_data())


def test_section_value_reads_a_scalar_parameter():
    section = _soul_section()

    assert section.value("party_restart_minutes") == 60
    assert section.value("default_party_id") == "FM15321640"


def test_section_value_falls_back_to_the_given_default():
    section = _soul_section()

    assert section.value("party_restart_minutes", 720) == 60
    assert section.value("never_configured", 720) == 720
    assert section.value("never_configured") is None


def test_section_require_raises_for_a_missing_parameter():
    section = _soul_section()

    with pytest.raises(MissingConfigKey) as excinfo:
        section.require("never_configured")

    assert excinfo.value.section == "soul"
    assert excinfo.value.key == "never_configured"


def test_section_maybe_section_reads_a_nested_section():
    section = _soul_section()

    nested = section.maybe_section("post_party_create")

    assert isinstance(nested, ConfigSectionView)
    assert nested.value("enabled") is True
    assert nested.require("commands") == [":skip"]
    assert section.maybe_section("nowhere") is None


def test_section_nested_section_raises_for_a_missing_nested_section():
    section = _soul_section()

    with pytest.raises(MissingConfigKey):
        section.section("nowhere")


def test_soul_section_parameters_are_read_through_the_view():
    """消费者读 soul 段参数只认视图方法。"""
    view = ConfigView({"soul": _soul_data()})
    soul = view.soul

    assert soul.value("party_restart_minutes", 720) == 60
    assert soul.value("default_party_id") == "FM15321640"
    assert soul.require("room_owner") == "Joyer"


def test_soul_elements_are_read_through_the_element_accessors():
    """选择器只从 .element() / .maybe_element() 出来，且是 Locator。"""
    soul = _soul_section()

    content = soul.element("message_content")
    assert isinstance(content, Locator)
    assert content.kind == "xpath"

    send_button = soul.element("button_send")
    assert isinstance(send_button, Locator)
    assert send_button.kind == "id"
    assert send_button.value == "cn.soulapp.android:id/btnSend"


def test_soul_element_missing_key_raises_missing_element_key():
    soul = _soul_section()

    assert soul.maybe_element("never_configured") is None

    with pytest.raises(MissingElementKey) as excinfo:
        soul.element("never_configured")

    assert excinfo.value.section == "soul"
    assert excinfo.value.key == "never_configured"


def test_config_view_exposes_the_soul_section():
    view = ConfigView({"soul": _soul_data(), "qq_music": {}})

    assert view.soul.name == "soul"
    assert view.soul is view.section("soul")
    assert view.soul is not view.music
