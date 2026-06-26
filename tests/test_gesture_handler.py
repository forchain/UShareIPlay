from types import SimpleNamespace

from ushareiplay.core.ui.gesture_handler import GestureHandler


class FakeLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class FakeDriver:
    def __init__(self):
        self.swipes = []

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms):
        self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))
        return None


def test_perform_swipe_uses_driver_swipe():
    driver = FakeDriver()
    handler = GestureHandler(SimpleNamespace(driver=driver, logger=FakeLogger(), config={}))

    assert handler._perform_swipe(10, 20, 30, 40, duration_ms=250) is True
    assert driver.swipes == [(10, 20, 30, 40, 250)]
