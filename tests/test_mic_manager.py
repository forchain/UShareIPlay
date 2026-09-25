"""MicManager：麦克风状态与开关的唯一实现。

本文件合并了原先三份针对同一行为的测试：
- tests/test_soul_handler_seat_take.py 的 ensure_mic_active 三例
- tests/test_mic_command_seat_precheck.py 的麦位/状态机件
- （:mic 命令只保留「决定目标状态并委托」的测试，见 test_mic_command_seat_precheck.py）

Ticket #317 的两个不变量现在都住在这里：
1. 开麦前必须先上麦（不在麦位时 UI 只提供抢麦入口）
2. 「开麦 = content-desc 是『闭麦按钮』」
"""

from ushareiplay.managers.mic_manager import MicManager


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def error(self, message):
        self.messages.append(("error", message))

    def debug(self, _message):
        pass


class _Element:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def click(self):
        self.events.append(f"click:{self.name}")


class _KeyActions:
    def switch_to_app(self):
        return True


class _ElementFinder:
    """房间 UI 替身：`grab_mic` 只在不在麦位时存在。"""

    def __init__(self, events, on_seat=False, mic_desc="开麦按钮", disappear_after_grab=True):
        self.events = events
        self.on_seat = on_seat
        self.mic_desc = mic_desc
        self.disappear_after_grab = disappear_after_grab
        self.missing_toggle = False
        self.disappear_calls = []
        self.waited_for = []
        self._grab_mic = _Element(events, "grab_mic")
        self._confirm_mic = _Element(events, "confirm_mic")
        self._toggle_mic = _Element(events, "toggle_mic")

    def try_find_element(self, key, log=False, clickable=False):
        if key == "grab_mic":
            return None if self.on_seat else self._grab_mic
        if key == "toggle_mic":
            return None if self.missing_toggle else self._toggle_mic
        return None

    def wait_for_element(self, key, timeout=None):
        """等按钮出现：假件不真的等，只记下「这里等了」。"""
        self.waited_for.append(key)
        return self.try_find_element(key)

    def wait_for_element_clickable(self, key, timeout=None):
        if key == "grab_mic":
            return None if self.on_seat else self._grab_mic
        if key == "confirm_mic":
            return self._confirm_mic
        if key == "toggle_mic":
            return None if self.missing_toggle else self._toggle_mic
        return None

    def wait_for_element_disappear(self, key, timeout=3.0, poll_frequency=0.1):
        self.disappear_calls.append((key, timeout))
        if key != "grab_mic":
            return True
        if self.disappear_after_grab:
            self.on_seat = True
        return self.on_seat

    def try_get_attribute(self, element, attribute):
        if element is self._toggle_mic and attribute == "content-desc":
            return self.mic_desc
        return None


class _SoulHandler:
    """SoulHandler 的麦位/麦克风机件替身。"""

    def __init__(self, events, on_seat=False, mic_desc="开麦按钮", seat_succeeds=True,
                 mic_on_after_seat=None, disappear_after_grab=True):
        self.events = events
        self.logger = _Logger()
        self.key_actions = _KeyActions()
        self.element_finder = _ElementFinder(
            events, on_seat=on_seat, mic_desc=mic_desc, disappear_after_grab=disappear_after_grab
        )
        self.seat_succeeds = seat_succeeds
        self.mic_on_after_seat = mic_on_after_seat

    def is_on_seat(self):
        return self.element_finder.on_seat

    def ensure_on_seat(self):
        self.events.append("ensure_on_seat")
        if not self.seat_succeeds:
            return False
        self.element_finder.on_seat = True
        if self.mic_on_after_seat is not None:
            self.element_finder.mic_desc = "闭麦按钮" if self.mic_on_after_seat else "开麦按钮"
        return True

    # MicManager 只通过 is_on_seat / ensure_on_seat 使用麦位；grab_mic_and_confirm
    # 由 SoulHandler 的 ensure_on_seat 内部调用，替身里合并进 ensure_on_seat。


def _make_manager(**kwargs):
    events = []
    handler = _SoulHandler(events, **kwargs)
    manager = MicManager.instance()
    manager._soul_handler = handler
    manager._logger = handler.logger
    return manager, handler, events


# --------------------------------------------------------------------------
# state()
# --------------------------------------------------------------------------

def test_state_is_true_when_the_desc_says_mic_is_open():
    manager, _handler, _events = _make_manager(mic_desc="闭麦按钮")
    assert manager.state() is True


def test_state_is_false_when_the_desc_says_mic_is_closed():
    manager, _handler, _events = _make_manager(mic_desc="开麦按钮")
    assert manager.state() is False


def test_state_is_unknown_for_an_unrecognized_desc():
    manager, _handler, _events = _make_manager(mic_desc="未知按钮")
    assert manager.state() is None


def test_state_is_unknown_when_the_button_is_absent():
    manager, handler, _events = _make_manager()
    handler.element_finder.missing_toggle = True
    assert manager.state() is None


def test_state_reads_without_waiting_unless_asked():
    """静音保护读态是非阻塞的：读不到就跳过，不该在这里等。"""
    manager, handler, _events = _make_manager(mic_desc="闭麦按钮")

    assert manager.state() is True
    assert handler.element_finder.waited_for == []


# --------------------------------------------------------------------------
# set_active()：开麦前必须先上麦
# --------------------------------------------------------------------------

def test_set_active_true_from_off_seat_takes_a_seat_first():
    manager, _handler, events = _make_manager(on_seat=False, mic_on_after_seat=False)

    assert manager.set_active(True) == {"state": "1"}
    assert events == ["ensure_on_seat", "click:toggle_mic"]


def test_set_active_true_when_already_seated_does_not_take_a_seat():
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="开麦按钮")

    assert manager.set_active(True) == {"state": "1"}
    assert events == ["click:toggle_mic"]


def test_set_active_false_never_touches_the_seat():
    manager, _handler, events = _make_manager(on_seat=False, mic_desc="闭麦按钮")

    assert manager.set_active(False) == {"state": "0"}
    assert events == ["click:toggle_mic"]


def test_set_active_reports_error_and_leaves_mic_untouched_when_seating_fails():
    manager, _handler, events = _make_manager(on_seat=False, seat_succeeds=False)

    result = manager.set_active(True)

    assert events == ["ensure_on_seat"]
    assert "error" in result
    assert "grab" in result["error"].lower()


def test_set_active_waits_for_the_button_instead_of_failing_fast():
    """要动手改麦克风就得等按钮出现：刚就座/刚进房时它可能还没渲染。

    即时读（try_find_element）会立刻判定「找不到按钮」并放弃，`:mic` 就变成了
    一次进房第一次按必然失败。
    """
    manager, handler, _events = _make_manager(on_seat=True, mic_desc="开麦按钮")

    assert manager.set_active(True) == {"state": "1"}
    assert handler.element_finder.waited_for == ["toggle_mic"]


def test_set_active_waits_after_taking_a_seat():
    """抢麦就座之后按钮才挂上界面 —— 这条读态同样要等。"""
    manager, handler, _events = _make_manager(on_seat=False, mic_on_after_seat=True)

    assert manager.set_active(True) == {"state": "1"}
    assert handler.element_finder.waited_for == ["toggle_mic"]


def test_set_active_reports_missing_toggle_button():
    manager, handler, _events = _make_manager(on_seat=True, mic_desc="开麦按钮")
    handler.element_finder.missing_toggle = True

    assert manager.set_active(True) == {"error": "Microphone button not found"}


def test_set_active_reports_unreadable_status_when_the_desc_is_unknown():
    manager, _handler, _events = _make_manager(on_seat=True, mic_desc="未知按钮")

    assert manager.set_active(True) == {"error": "Failed to get mic status"}


def test_set_active_is_idempotent_by_default():
    """静音保护与 :pause 用默认语义：目标状态已达成就是成功，不是错误。"""
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="闭麦按钮")

    assert manager.set_active(True) == {"state": "1"}
    assert events == []


def test_set_active_reports_already_on_when_asked_to():
    """:mic 1 用 report_noop 保持「已开麦」提示。"""
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="闭麦按钮")

    assert manager.set_active(True, report_noop=True) == {"error": "Microphone is already on"}
    assert events == []


def test_set_active_reports_already_off_when_asked_to():
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="开麦按钮")

    assert manager.set_active(False, report_noop=True) == {"error": "Microphone is already off"}
    assert events == []


def test_set_active_after_seating_with_mic_already_open_is_success_not_noop():
    """抢麦就座后麦克风已随座位自动打开：这是成功，不是「已开麦」。"""
    manager, _handler, events = _make_manager(on_seat=False, mic_on_after_seat=True)

    assert manager.set_active(True, report_noop=True) == {"state": "1"}
    assert events == ["ensure_on_seat"]


# --------------------------------------------------------------------------
# ensure_active()：静音保护的兜底恢复
# --------------------------------------------------------------------------

def test_ensure_active_grabs_the_mic_when_off_seat():
    manager, _handler, events = _make_manager(on_seat=False, mic_on_after_seat=True)

    assert manager.ensure_active() == {"state": "1"}
    assert events == ["ensure_on_seat"]


def test_ensure_active_turns_on_a_muted_mic_when_seated():
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="开麦按钮")

    assert manager.ensure_active() == {"state": "1"}
    assert events == ["click:toggle_mic"]


def test_ensure_active_leaves_an_open_mic_alone():
    manager, _handler, events = _make_manager(on_seat=True, mic_desc="闭麦按钮")

    assert manager.ensure_active() == {"state": "1"}
    assert events == []


def test_ensure_active_swallows_exceptions_instead_of_raising():
    """兜底恢复发生在已经出错的播放流程里，不能再把异常抛回去。"""
    manager, handler, _events = _make_manager(on_seat=True)

    def boom():
        raise RuntimeError("UI connection severed")

    handler.is_on_seat = boom

    result = manager.ensure_active()

    assert "error" in result
    assert "UI connection severed" in result["error"]
