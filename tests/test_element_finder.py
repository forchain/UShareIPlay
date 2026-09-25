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


def test_wait_for_any_element_with_distinct_element_instances():
    """
    In Appium, finding an element multiple times returns distinct WebElement instances
    with different IDs. wait_for_any_element must correctly identify the matching key
    without failing on element ID equality.
    """
    owner = _Owner()
    owner.config = {
        "elements": {
            "party_back": "cn.soulapp.android:id/tv_look",
            "search_entry": "cn.soulapp.android:id/ivSearch",
        }
    }
    finder = ElementFinder(owner)

    elem_found = MagicMock()
    elem_found.id = "appium-uuid-1"

    call_count = 0

    def mock_find_element(by, value):
        nonlocal call_count
        call_count += 1
        if value == "cn.soulapp.android:id/tv_look":
            elem = MagicMock()
            elem.id = f"appium-uuid-{call_count}"
            return elem
        raise RuntimeError("not found")

    owner.driver.find_element.side_effect = mock_find_element

    key, elem = finder.wait_for_any_element(["party_back", "search_entry"], timeout=1)
    assert key == "party_back"
    assert elem is not None


def test_wait_for_any_element_respects_priority_order():
    """When multiple elements are present, the one specified earlier in element_keys takes precedence."""
    owner = _Owner()
    owner.config = {
        "elements": {
            "party_back": "cn.soulapp.android:id/tv_look",
            "search_entry": "cn.soulapp.android:id/ivSearch",
        }
    }
    finder = ElementFinder(owner)

    back_elem = MagicMock()
    search_elem = MagicMock()

    def mock_find_element(by, value):
        if value == "cn.soulapp.android:id/tv_look":
            return back_elem
        if value == "cn.soulapp.android:id/ivSearch":
            return search_elem
        raise RuntimeError("not found")

    owner.driver.find_element.side_effect = mock_find_element

    # party_back listed first -> returns party_back
    key, elem = finder.wait_for_any_element(["party_back", "search_entry"], timeout=1)
    assert key == "party_back"
    assert elem is back_elem

    # search_entry listed first -> returns search_entry
    key, elem = finder.wait_for_any_element(["search_entry", "party_back"], timeout=1)
    assert key == "search_entry"
    assert elem is search_elem


def test_wait_for_any_element_timeout():
    owner = _Owner()
    owner.config = {
        "elements": {
            "party_back": "cn.soulapp.android:id/tv_look",
        }
    }
    finder = ElementFinder(owner)
    owner.driver.find_element.side_effect = RuntimeError("never found")

    key, elem = finder.wait_for_any_element(["party_back"], timeout=0.1)
    assert key is None
    assert elem is None
    owner.logger.error.assert_called_once()


def test_wait_for_any_element_no_valid_keys():
    owner = _Owner()
    owner.config = {"elements": {}}
    finder = ElementFinder(owner)

    key, elem = finder.wait_for_any_element(["non_existent"], timeout=1)
    assert key is None
    assert elem is None
    owner.logger.warning.assert_called_once_with("wait_for_any_element: 没有有效的元素key")


