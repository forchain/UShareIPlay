"""会随交互改变状态的假界面。

「失败后必须退干净」这类契约，只有在可见元素跟着点击变化时才测得出来。
原先那批用例靠硬编码断言 `press_back()` 的调用次数（1/2/3 次），界面状态
始终不变，于是「退了几层」和「界面干净了」被混为一谈 —— 少退一层照样绿。

`FakeScreen` 把界面建模成由外到内的层栈：点开一个弹窗就是压一层，返回键
弹掉最上面一层，弹到空栈还按返回就记一次误退（stray_back）。这样断言的是
「结束时没有残留层、没有误退」，而不是某个魔法次数。
"""

from types import SimpleNamespace


class FakeElement:
    """被点击/输入时可改变屏幕状态的假元素。"""

    def __init__(self, key="", screen=None, on_click=None, text=""):
        self.key = key
        self.screen = screen
        self.on_click = on_click
        self.text = text
        self.clicks = 0
        self.cleared = 0
        self.sent_keys = []
        self.sends = []  # send_keys 收到的参数

    def click(self):
        self.clicks += 1
        if self.on_click is not None:
            self.on_click()

    def clear(self):
        self.cleared += 1

    def send_keys(self, value):
        self.sent_keys.append(value)
        self.sends.append(value)


class FakeElementFinder:
    """按 FakeScreen 的层栈回答「这个元素现在在不在」。

    always      —— 始终存在的元素（主界面房名、抽屉里的编辑铅笔…），返回原型
                   本身，因此它们的点击副作用会真的发生。
    conditional —— key -> (predicate, prototype)：predicate(screen) 为真时才算
                   存在，用来表达「这层弹窗没开，所以它不在」。
    """

    def __init__(self, screen, elements=None, conditional=None, logger=None):
        self.screen = screen
        self.always = dict(elements or {})
        self.conditional = dict(conditional or {})
        self.logger = logger
        self.waited = []
        self.clicked_waited = []

    def try_find_element(self, key, log=False, clickable=False):
        if key in self.always:
            return self.always[key]
        entry = self.conditional.get(key)
        if entry and entry[0](self.screen):
            return entry[1]
        if key in self.screen.open_keys:
            return FakeElement(key, self.screen)
        return None

    def try_find_any_element(self, keys):
        for key in keys:
            element = self.try_find_element(key)
            if element:
                return key, element
        return None, None

    def get_element_text(self, element):
        return getattr(element, "text", "")

    # -- 等待读 -----------------------------------------------------------

    def wait_for_element(self, key, timeout=10):
        self.waited.append(key)
        return self.try_find_element(key)

    def wait_for_element_clickable(self, key, timeout=10):
        self.clicked_waited.append(key)
        return self.try_find_element(key)

    def wait_for_any_element(self, keys, timeout=10):
        return self.try_find_any_element(keys)


class FakeScreen:
    """由外到内的弹窗层栈；返回键弹掉最上面一层。"""

    def __init__(self, *layers):
        self.layers = list(layers)
        self.backs = 0
        self.stray_backs = 0

    # -- 状态 -------------------------------------------------------------

    @property
    def open_keys(self):
        return set(self.layers)

    def is_clean(self):
        return not self.layers

    def open(self, name):
        if name not in self.layers:
            self.layers.append(name)

    def close(self, *names):
        for name in names:
            if name in self.layers:
                self.layers.remove(name)

    def back(self):
        """返回键：弹掉最上层；已经干净还按，算一次误退。"""
        self.backs += 1
        if not self.layers:
            self.stray_backs += 1
            return False
        self.layers.pop()
        return True

    def __contains__(self, name):
        return name in self.layers


class FakeLogger:
    """记录各级别日志，便于断言「没有输出误导性超时警告」。"""

    def __init__(self):
        self.records = []

    def _record(self, level):
        def _log(msg, *args, **kwargs):
            try:
                self.records.append((level, str(msg % args if args else msg)))
            except Exception:
                self.records.append((level, str(msg)))
        return _log

    def __getattr__(self, name):
        return self._record(name)

    def messages(self, level=None):
        if level is None:
            return [text for _lvl, text in self.records]
        return [text for lvl, text in self.records if lvl == level]

    def mentions(self, needle, level=None):
        return any(needle in text for text in self.messages(level))


class FakeKeyActions:
    def __init__(self, screen, switch_to_app=True):
        self.screen = screen
        self.switch_result = switch_to_app
        self.switches = 0

    def press_back(self):
        self.screen.back()

    def switch_to_app(self):
        self.switches += 1
        return self.switch_result


class FakeUIActions:
    """点成功就真的把对应层压上去，否则「只关自己开的那一次」无从观察。"""

    def __init__(self, screen, on_open=None, fail_for=()):
        self.screen = screen
        self.on_open = on_open or (lambda key: None)
        self.fail_for = set(fail_for)
        self.clicks = []

    def switch_and_click(self, key, *, error_message=None, **_kw):
        self.clicks.append(key)
        if key in self.fail_for:
            return {"error": error_message}
        self.on_open(key)
        return {"success": True}


def bind_room_info_window(handler):
    """把假 handler 注入 RoomInfoWindow —— 抽屉的开关归它所有。"""
    from ushareiplay.managers.room_info_window import RoomInfoWindow

    window = RoomInfoWindow.instance()
    window._handler = handler
    window._logger = handler.logger
    return window


def make_handler(screen, *, elements=None, conditional=None, fail_for=(), on_open=None, config=None):
    """拼一个够用的假 handler：screen 驱动可见性，logger 记录日志。"""
    logger = FakeLogger()
    finder = FakeElementFinder(screen, elements=elements, conditional=conditional, logger=logger)

    class _Gestures:
        @staticmethod
        def click_element_at(element, *a, **k):
            # 坐标点击同样会把目标弹窗点出来
            element.click()
            return True

    return SimpleNamespace(
        logger=logger,
        config=config or {},
        element_finder=finder,
        key_actions=FakeKeyActions(screen),
        ui_actions=FakeUIActions(screen, on_open=on_open, fail_for=fail_for),
        gesture_handler=_Gestures,
        controller=None,
    )