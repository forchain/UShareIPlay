from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from ushareiplay.managers.topic_manager import TopicManager


@pytest.fixture(autouse=True)
def _reset_topic_manager():
    TopicManager.reset_instance()
    yield
    TopicManager.reset_instance()


class _FakeSoulHandler:
    def __init__(self):
        self.logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True


def test_change_topic_sanitizes_fullwidth_pipe_and_parentheses():
    manager = TopicManager.initialize()
    manager._soul_handler = _FakeSoulHandler()

    result = manager.change_topic("经典老歌（粤语）｜extra")

    assert manager.next_topic == "经典老歌"
    assert "Topic will update soon" in result["topic"]


def test_change_topic_sanitizes_halfwidth_pipe_and_parentheses():
    manager = TopicManager.initialize()
    manager._soul_handler = _FakeSoulHandler()

    result = manager.change_topic("流行金曲 (国语) | extra")

    assert manager.next_topic == "流行金曲"
    assert "Topic will update soon" in result["topic"]
