from unittest.mock import MagicMock

from ushareiplay.core.ui.element_finder import ElementFinder


class _Owner:
    def __init__(self):
        self.driver = MagicMock()
        self.logger = MagicMock()
        self.config = {"elements": {"child": "child-id"}}


def test_find_child_element_can_suppress_failure_log():
    owner = _Owner()
    parent = MagicMock()
    parent.find_element.side_effect = RuntimeError("missing")
    finder = ElementFinder(owner)

    assert finder.find_child_element(parent, "child", log_failure=False) is None

    owner.logger.debug.assert_not_called()


def test_find_child_element_logs_failure_by_default():
    owner = _Owner()
    parent = MagicMock()
    parent.find_element.side_effect = RuntimeError("missing")
    finder = ElementFinder(owner)

    assert finder.find_child_element(parent, "child") is None

    owner.logger.debug.assert_called_once_with("Failed to find child element child")
