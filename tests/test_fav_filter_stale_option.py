from selenium.common.exceptions import StaleElementReferenceException

from ushareiplay.commands.fav import FavCommand


class FakeLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


class FakeElement:
    def __init__(self, text="", stale_clicks=0, stale_enabled_checks=0):
        self.text = text
        self.stale_clicks = stale_clicks
        self.stale_enabled_checks = stale_enabled_checks
        self.clicks = 0

    def is_displayed(self):
        return True

    def is_enabled(self):
        if self.stale_enabled_checks:
            self.stale_enabled_checks -= 1
            raise StaleElementReferenceException("stale enabled check")
        return True

    def click(self):
        self.clicks += 1
        if self.stale_clicks:
            self.stale_clicks -= 1
            raise StaleElementReferenceException("stale option")


class FakeDriver:
    def __init__(self):
        self.option_stale = FakeElement(stale_clicks=1)
        self.option_fresh = FakeElement()
        self.confirm = FakeElement(text="确定（12首）")
        self.find_calls = []

    def find_element(self, by, value):
        self.find_calls.append((by, value))
        if value == '//android.widget.TextView[@text="英语"]':
            option_calls = [
                call for call in self.find_calls if call[1] == '//android.widget.TextView[@text="英语"]'
            ]
            if len(option_calls) == 1:
                return self.option_stale
            return self.option_fresh
        if value == '//android.widget.TextView[starts-with(@text,"确定（") and contains(@text,"首）")]':
            return self.confirm
        raise AssertionError(f"Unexpected locator: {value}")


class FakeHandler:
    def __init__(self):
        self.driver = FakeDriver()
        self.logger = FakeLogger()
        self.filter = FakeElement()

    def wait_for_element_clickable(self, key):
        assert key == "filter_favourite"
        return self.filter


class FakeController:
    def __init__(self):
        self.music_handler = FakeHandler()
        self.soul_handler = object()


def test_apply_favourite_filter_refinds_stale_option_before_clicking():
    command = FavCommand(FakeController())

    result = command._apply_favourite_filter_keyword("英语")

    assert result == {"count": 12}
    assert command.handler.filter.clicks == 1
    assert command.handler.driver.option_stale.clicks == 1
    assert command.handler.driver.option_fresh.clicks == 1
    assert command.handler.driver.confirm.clicks == 1


def test_click_xpath_refinds_option_when_clickable_check_goes_stale():
    command = FavCommand(FakeController())
    command.handler.driver.option_stale = FakeElement(stale_enabled_checks=1)

    clicked = command._click_xpath_with_stale_retry(
        '//android.widget.TextView[@text="英语"]',
        "Favourite filter option '英语'",
    )

    assert clicked is command.handler.driver.option_fresh
    assert command.handler.driver.option_stale.clicks == 0
    assert command.handler.driver.option_fresh.clicks == 1
