import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from ushareiplay.managers.room_name_manager import RoomNameManager


@pytest.fixture(autouse=True)
def _reset_room_name_manager():
    RoomNameManager.reset_instance()
    yield
    RoomNameManager.reset_instance()


class _FakeHandler:
    def __init__(self):
        self.logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
        self.element_finder = MagicMock()
        self.element_finder.try_find_element.return_value = None
        self.gesture_handler = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = False
        self.ui_actions = MagicMock()


def _manager_with_fake_handler():
    manager = RoomNameManager.initialize()
    manager._handler = _FakeHandler()
    return manager


@pytest.mark.asyncio
async def test_set_theme_updates_current_theme_and_marks_pending():
    manager = _manager_with_fake_handler()

    result = manager.set_theme("助眠")

    assert result["success"] is True
    assert manager.get_current_theme() == "助眠"
    assert manager.has_pending_ui_update() is True


def test_set_theme_rejects_too_long_theme():
    manager = _manager_with_fake_handler()
    assert "error" in manager.set_theme("太长了")


def test_can_update_now_respects_cooldown():
    manager = _manager_with_fake_handler()
    assert manager.can_update_now() is True
    manager._advance_cooldown()
    assert manager.can_update_now() is False


def test_get_remaining_cooldown_minutes_after_cooldown_set():
    manager = _manager_with_fake_handler()
    manager.cooldown_minutes = 10
    manager._advance_cooldown()
    assert manager.get_remaining_cooldown_minutes() <= 10
    assert manager.get_remaining_cooldown_minutes() >= 0


def test_set_next_title_sanitizes_and_queues_title():
    manager = _manager_with_fake_handler()
    manager._handler.ui_actions.switch_and_click.return_value = {}

    result = manager.set_next_title("Hello (world) | extra")

    assert manager.get_next_title() == "Hello"
    assert "Title will update" in result["title"]


def test_set_next_title_with_theme_updates_theme_too():
    manager = _manager_with_fake_handler()
    manager._handler.ui_actions.switch_and_click.return_value = {}

    manager.set_next_title("My Title", theme="新")

    assert manager.get_current_theme() == "新"
    assert manager.get_next_title() == "My Title"


def test_set_next_title_returns_error_when_switch_fails():
    manager = _manager_with_fake_handler()
    manager._handler.ui_actions.switch_and_click.return_value = {"error": "boom"}

    result = manager.set_next_title("Title")
    assert "error" in result


def test_process_pending_update_skips_when_cooldown_active():
    manager = _manager_with_fake_handler()
    manager._advance_cooldown()
    manager.next_title = "Pending"

    result = manager.process_pending_update()

    assert result["cooldown"] is True
    assert manager.get_next_title() == "Pending"


def test_process_pending_update_skips_when_nothing_pending():
    manager = _manager_with_fake_handler()

    result = manager.process_pending_update()

    assert result["skipped"] is True


def test_process_pending_update_writes_ui_when_ready():
    manager = _manager_with_fake_handler()
    manager.next_title = "New Title"
    manager._handler.key_actions.switch_to_app.return_value = True

    fake_element = MagicMock()
    manager._handler.element_finder.wait_for_element_clickable.return_value = fake_element
    manager._handler.gesture_handler.click_element_at.return_value = True
    manager._handler.element_finder.wait_for_any_element.return_value = ("title_edit_entry", fake_element)
    manager._handler.element_finder.try_find_element.return_value = None

    result = manager.process_pending_update()

    assert result["ui_updated"] is True
    assert manager.get_current_title() == "New Title"
    assert manager.get_next_title() is None
    assert manager.has_pending_ui_update() is False


def test_initialize_from_ui_parses_theme_and_title():
    manager = _manager_with_fake_handler()
    fake_element = MagicMock()
    manager._handler.element_finder.try_find_element.return_value = fake_element
    manager._handler.element_finder.get_element_text.return_value = "助眠｜晚安"

    result = manager.initialize_from_ui()

    assert result["initialized"] is True
    assert manager.get_current_theme() == "助眠"
    assert manager.get_current_title() == "晚安"
    assert manager.is_initialized is True


def test_initialize_from_ui_falls_back_when_no_separator():
    manager = _manager_with_fake_handler()
    fake_element = MagicMock()
    manager._handler.element_finder.try_find_element.return_value = fake_element
    manager._handler.element_finder.get_element_text.return_value = "JustATitle"

    manager.initialize_from_ui()

    assert manager.get_current_title() == "JustATitle"
    assert manager.is_initialized is True
