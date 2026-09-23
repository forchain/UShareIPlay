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


def test_wait_for_element_disappear_success(monkeypatch):
    owner = _Owner()
    finder = ElementFinder(owner)

    class FakeUntil:
        def __init__(self, driver, timeout, poll_frequency=0.1):
            pass

        def until(self, ec):
            return True

    monkeypatch.setattr("ushareiplay.core.ui.element_finder.WebDriverWait", FakeUntil)

    assert finder.wait_for_element_disappear("child", timeout=1.0) is True


def test_wait_for_element_disappear_timeout(monkeypatch):
    owner = _Owner()
    finder = ElementFinder(owner)

    from selenium.common.exceptions import TimeoutException

    class FakeUntilTimeout:
        def __init__(self, driver, timeout, poll_frequency=0.1):
            pass

        def until(self, ec):
            raise TimeoutException("element still visible")

    monkeypatch.setattr("ushareiplay.core.ui.element_finder.WebDriverWait", FakeUntilTimeout)

    assert finder.wait_for_element_disappear("child", timeout=1.0) is False
