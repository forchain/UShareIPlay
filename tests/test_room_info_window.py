"""RoomInfoWindow 的接口测试。

取代原先的 tests/test_room_info_auditor.py —— 审计职责已并入本模块，
因此「窗口什么时候开着、关窗归谁、窗口内的顺序」现在一起被测。
"""

from types import SimpleNamespace

from ushareiplay.managers.room_info_window import RoomInfoWindow


class _Logger:
    def info(self, _msg):
        pass

    def warning(self, _msg):
        pass

    def error(self, _msg):
        pass


class _ElementFinder:
    def __init__(self, elements=None):
        self.elements = dict(elements or {})
        self.queries = []

    def try_find_element(self, key, log=False):
        self.queries.append(key)
        return self.elements.get(key)


class _KeyActions:
    def __init__(self):
        self.back_presses = 0

    def press_back(self):
        self.back_presses += 1


class _UIActions:
    """点击成功就真的把抽屉打开 —— 否则「只关自己开的那一次」无从观察。"""

    def __init__(self, finder, fail_for=()):
        self.finder = finder
        self.clicks = []
        self.fail_for = set(fail_for)

    def switch_and_click(self, key, *, error_message, **_kw):
        self.clicks.append(key)
        if key in self.fail_for:
            return {"error": error_message}
        self.finder.elements["slide_drawer"] = object()
        return {"success": True}


def _handler(elements=None, fail_for=()):
    finder = _ElementFinder(elements)
    return SimpleNamespace(
        logger=_Logger(),
        element_finder=finder,
        key_actions=_KeyActions(),
        ui_actions=_UIActions(finder, fail_for),
    )


def _window(handler):
    RoomInfoWindow.reset_instance()
    window = RoomInfoWindow.initialize()
    window._handler = handler
    window._logger = handler.logger
    return window


# --------------------------------------------------------------------------
# 检测
# --------------------------------------------------------------------------

def test_is_open_true_when_any_dialog_marker_is_present():
    for marker in (
        "party_room_type_option",
        "party_recommendation_status",
        "edit_topic_entry",
        "edit_notice_entry",
        "slide_drawer",
    ):
        window = _window(_handler({marker: object()}))
        assert window.is_open() is True


def test_is_open_false_when_nothing_present():
    window = _window(_handler())
    assert window.is_open() is False


def test_is_open_false_without_a_handler():
    RoomInfoWindow.reset_instance()
    window = RoomInfoWindow.initialize()
    window._handler = None
    assert window.is_open() is False


# --------------------------------------------------------------------------
# 打开
# --------------------------------------------------------------------------

def test_ensure_open_is_a_noop_when_already_open():
    handler = _handler({"slide_drawer": object()})
    window = _window(handler)

    assert window.ensure_open() is None
    assert handler.ui_actions.clicks == []


def test_ensure_open_uses_the_first_entry_that_works():
    handler = _handler()
    window = _window(handler)

    assert window.ensure_open(("chat_room_title", "room_topic")) is None
    assert handler.ui_actions.clicks == ["chat_room_title"]


def test_ensure_open_falls_back_to_the_next_entry():
    handler = _handler(fail_for=("chat_room_title",))
    window = _window(handler)

    assert window.ensure_open(("chat_room_title", "room_topic")) is None
    assert handler.ui_actions.clicks == ["chat_room_title", "room_topic"]


def test_ensure_open_reports_an_error_when_every_entry_fails():
    handler = _handler(fail_for=("chat_room_title", "room_topic"))
    window = _window(handler)

    assert "error" in window.ensure_open(("chat_room_title", "room_topic"))


# --------------------------------------------------------------------------
# 关闭
# --------------------------------------------------------------------------

def test_ensure_closed_is_a_noop_when_already_closed():
    handler = _handler()
    window = _window(handler)

    window.ensure_closed()
    assert handler.key_actions.back_presses == 0


def test_ensure_closed_prefers_close_drawer_over_press_back():
    from ushareiplay.managers.recovery_manager import RecoveryManager

    handler = _handler({"party_room_type_option": object()})
    window = _window(handler)

    calls = []

    class _Recovery:
        def close_drawer(self, drawer_key, **_kw):
            calls.append(drawer_key)
            return True

    RecoveryManager._instance = _Recovery()
    RecoveryManager._singleton_initialized = True
    try:
        window.ensure_closed()
    finally:
        RecoveryManager.reset_instance()

    assert calls == ["slide_drawer"]
    assert handler.key_actions.back_presses == 0


def test_ensure_closed_falls_back_to_press_back_when_close_drawer_fails():
    from ushareiplay.managers.recovery_manager import RecoveryManager

    handler = _handler({"party_room_type_option": object()})
    window = _window(handler)

    class _Recovery:
        def close_drawer(self, drawer_key, **_kw):
            return False

    RecoveryManager._instance = _Recovery()
    RecoveryManager._singleton_initialized = True
    try:
        window.ensure_closed()
    finally:
        RecoveryManager.reset_instance()

    assert handler.key_actions.back_presses == 1


# --------------------------------------------------------------------------
# with_window_open：只关自己打开的那一次
# --------------------------------------------------------------------------

def test_with_window_open_closes_a_window_it_opened():
    handler = _handler()
    window = _window(handler)

    with window.with_window_open() as open_error:
        assert open_error is None

    assert handler.ui_actions.clicks == ["chat_room_title"]
    assert handler.key_actions.back_presses == 1


def test_with_window_open_leaves_an_already_open_window_alone():
    """窗口是外层流程打开的时候，退出后必须保持开着，由外层决定何时关。"""
    handler = _handler({"slide_drawer": object()})
    window = _window(handler)

    with window.with_window_open() as open_error:
        assert open_error is None

    assert handler.ui_actions.clicks == []
    assert handler.key_actions.back_presses == 0


def test_with_window_open_yields_the_error_and_does_not_close_when_it_cannot_open():
    handler = _handler(fail_for=("chat_room_title", "room_topic"))
    window = _window(handler)

    with window.with_window_open() as open_error:
        assert "error" in open_error

    assert handler.key_actions.back_presses == 0


# --------------------------------------------------------------------------
# 窗口内的顺序与全量审计
# --------------------------------------------------------------------------

def _stub_managers(monkeypatch, recorder):
    from ushareiplay.managers.room_profile import RoomProfileManager

    def _inspect_current_ui_status(self, wait=True):
        recorder['recommendation_wait'] = wait
        return recorder.setdefault('recommendation', True) and True

    # 推荐分发与派对类型都成了 RoomProfileManager 自己的字段（#393），
    # 不再由两个 legacy 单例在背后提供。
    monkeypatch.setattr(
        RoomProfileManager,
        "inspect_current_ui_status",
        _inspect_current_ui_status,
    )
    monkeypatch.setattr(
        RoomProfileManager,
        "sync_and_correct_room_type_if_dialog_open",
        lambda self: {'success': True},
    )
    # 房名也是 RoomProfileManager 自己的字段了（#392），直接替换掉那个内部方法。
    monkeypatch.setattr(
        RoomProfileManager,
        "initialize_from_ui",
        lambda self: {'success': True},
    )
    # 公告这一步是房间档案模块自己的字段（#391），不再是另一个单例。
    monkeypatch.setattr(
        RoomProfileManager,
        "_audit_notice_in_open_window",
        lambda self: {'success': True},
    )


def test_audit_and_repair_runs_the_four_steps_and_closes(monkeypatch):
    handler = _handler()
    window = _window(handler)
    recorder = {}
    _stub_managers(monkeypatch, recorder)

    results = window.audit_and_repair()

    assert set(results) == {'recommendation', 'room_type', 'room_name', 'notice'}
    assert window.pending_audit_retry is False
    # 窗口是它自己刚打开的，字段可能还没渲染 -> 等
    assert recorder['recommendation_wait'] is True
    # 窗口是它打开的 -> 结束后关窗
    assert handler.key_actions.back_presses == 1


def test_audit_and_repair_marks_pending_retry_when_a_step_fails(monkeypatch):
    handler = _handler()
    window = _window(handler)
    _stub_managers(monkeypatch, {})

    from ushareiplay.managers.room_profile import RoomProfileManager
    monkeypatch.setattr(
        RoomProfileManager,
        "sync_and_correct_room_type_if_dialog_open",
        lambda self: {'error': 'boom'},
    )

    window.audit_and_repair()

    assert window.pending_audit_retry is True


def test_audit_and_repair_is_skipped_in_a_guest_room(monkeypatch):
    from ushareiplay.state.room_state import RoomState

    handler = _handler()
    window = _window(handler)
    monkeypatch.setattr(RoomState, "_instance", SimpleNamespace(is_guest_room=True), raising=False)
    monkeypatch.setattr(RoomState, "_singleton_initialized", True, raising=False)

    assert window.audit_and_repair() == {'skipped': True, 'reason': 'guest_room'}


def test_sync_while_open_corrects_recommendation_status_before_editing(monkeypatch):
    """先纠偏再编辑：_sync_recommendation 必须回写 RoomState。"""
    handler = _handler()
    window = _window(handler)

    seen_wait = []

    def _inspect_current_ui_status(self, wait=True):
        seen_wait.append(wait)
        return False

    from ushareiplay.managers.room_profile import RoomProfileManager
    from ushareiplay.state.room_state import RoomState
    monkeypatch.setattr(RoomProfileManager, "inspect_current_ui_status", _inspect_current_ui_status)
    room_state = RoomState.initialize()

    results = window.sync_while_open()

    assert results['recommendation'] == {'success': True, 'status': False}
    assert room_state.recommendation_enabled is False
    # 被动路径（标题更新时窗口已经开着）读状态不等：布局里没有该字段时，
    # 等待会白等满整个超时，把每次改标题都拖住。
    assert seen_wait == [False]
