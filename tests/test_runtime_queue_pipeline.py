import asyncio
from types import SimpleNamespace
import logging
from collections import deque


def _run(coro):
    return asyncio.run(coro)


def _with_ui_components(handler):
    handler.key_actions = handler
    handler.gesture_handler = handler
    handler.element_finder = handler
    return handler


class _FakeObs:
    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class _FakeHandler:
    def __init__(self):
        self.sent = []
        self.logger = logging.getLogger("test_runtime_queue")
        self.config = {"logging": {"directory": "logs"}}
        self.controller = None

    def send_message(self, message):
        self.sent.append(message)


class _FakeCommandManager:
    def __init__(self):
        self.received = []

    async def execute_command_messages(self, messages):
        self.received.extend(messages)
        return len(messages)

    async def execute_runtime_queue_messages(self, queue_messages, send_screen_message=None):
        from ushareiplay.managers.command_manager import CommandManager

        manager = CommandManager.__new__(CommandManager)
        manager.__init__()
        manager._logger = logging.getLogger("test_runtime_queue_fake_command_manager")
        manager.execute_command_messages = self.execute_command_messages
        return await manager.execute_runtime_queue_messages(
            queue_messages,
            send_screen_message=send_screen_message,
        )


class _FakeWrapper:
    def __init__(self, content):
        self.content = content


def test_runtime_queue_drainer_routes_commands_and_plain_messages():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello {user_name};:timer list", nickname="Alice")))

    obs = _FakeObs()
    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, obs=obs, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello Alice"]
    assert [m.content for m in command_manager.received] == [":timer list"]
    assert [m.nickname for m in command_manager.received] == ["Alice"]
    assert [e[0] for e in obs.events] == ["queue.drain.start", "queue.drain.end"]


def test_runtime_queue_drainer_propagates_silent_commands_and_suppresses_plain_messages():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(content="hello {user_name};:timer list", nickname="Alice", silent=True)
        )
    )

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in command_manager.received] == [":timer list"]
    assert [m.silent for m in command_manager.received] == [True]


def test_runtime_queue_drainer_propagates_sleep_exempt_to_split_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(
        queue.put_message(
            MessageInfo(
                content=":mode random;:playlist Sugar",
                nickname="Alice",
                sleep_exempt=True,
            )
        )
    )

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 2
    assert [m.content for m in command_manager.received] == [":mode random", ":playlist Sugar"]
    assert [m.sleep_exempt for m in command_manager.received] == [True, True]


def test_runtime_queue_drainer_treats_slash_parts_as_silent_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello;/timer list", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello"]
    assert [m.content for m in command_manager.received] == ["/timer list"]
    assert [m.silent for m in command_manager.received] == [True]


def test_runtime_queue_drainer_routes_dollar_parts_as_private_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="hello;$info", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == ["hello"]
    assert [m.content for m in command_manager.received] == ["$info"]
    assert [m.nickname for m in command_manager.received] == ["Alice"]


def test_runtime_queue_drainer_routes_fullwidth_dollar_parts_as_private_commands():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo

    queue = MessageQueue.instance()
    _run(queue.clear_queue())
    _run(queue.put_message(MessageInfo(content="＄info", nickname="Alice")))

    handler = _FakeHandler()
    command_manager = _FakeCommandManager()
    drainer = RuntimeQueueDrainer(
        handler=handler, command_manager=command_manager, send_screen_message=handler.send_message, logger=handler.logger
    )

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert handler.sent == []
    assert [m.content for m in command_manager.received] == ["＄info"]


def _queue_after_scan(*lines):
    """Run lines through the real scan site and return what it queued."""
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    manager = MessageManager.instance()
    manager._handler = _with_ui_components(_FakeSoulHandler())
    manager._chat_logger = logging.getLogger("test_chat_logger_new")
    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    _run(manager.dispatch_intake(list(lines), room_owner="群主"))
    return list(_run(queue.get_all_messages()).values())


def test_screen_scan_queues_dollar_prefix_and_keeps_content():
    queued = _queue_after_scan("souler[Alice]说：$play 123")

    assert [m.content for m in queued] == ["$play 123"]
    assert [m.nickname for m in queued] == ["Alice"]


def test_screen_scan_queues_fullwidth_dollar_prefix_and_keeps_content():
    queued = _queue_after_scan("souler[Alice]说：＄info")

    assert [m.content for m in queued] == ["＄info"]
    assert [m.nickname for m in queued] == ["Alice"]


def test_screen_scan_skips_non_command_and_queues_following_dollar_command():
    # 两句都是"新"的：第一句是普通发言，第二句是命令
    queued = _queue_after_scan(
        "souler[Alice]说：hello", "souler[Alice]说：$play 123"
    )

    assert [m.content for m in queued] == ["$play 123"]


def test_screen_scan_queues_ascii_colon_in_chat_prefix():
    queued = _queue_after_scan("souler[Alice]说:$info")

    assert [m.content for m in queued] == ["$info"]


def test_process_new_messages_switches_to_app_without_executing_commands():
    """The scan still brings Soul forward; execution belongs to the drainer (#398)."""
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    switches = []

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_switch")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            switches.append(True)
            return True

    original_cmd_instance = CommandManager.instance
    try:
        # A bare object: `process_new_messages` has no execution entry point to
        # call any more (#399), so touching one would raise rather than pass quietly.
        CommandManager.instance = classmethod(lambda cls: object())
        manager = MessageManager.instance()
        manager._handler = _with_ui_components(_FakeSoulHandler())
        manager._chat_logger = logging.getLogger("test_chat_logger_switch")
        queue = MessageQueue.instance()
        _run(queue.clear_queue())
        manager.observe(["souler[Alice]说：$play 123"])

        assert _run(manager.process_new_messages()) is None

        assert switches == [True]  # D10: the UI switch stays at scan time
        assert queue.get_queue_size() == 0  # enqueueing belongs to dispatch_intake
    finally:
        CommandManager.instance = original_cmd_instance


def test_queued_screen_command_inherits_ambient_command_silence(chat_window, monkeypatch):
    """D9: routing screen commands through `MessageQueue` makes them obey
    `is_command_silent()`.

    `MessageQueue.put_message` force-silences anything enqueued while a command is
    executing (`message_queue.py`). The real-time path never called it before
    #398, so a screen command typed during another command's execution would still
    answer publicly. Unifying the two sources is exactly this behaviour change, so
    it is pinned here deliberately rather than left to be discovered in a live room.
    """
    from ushareiplay.core.command_silence import command_silence
    from ushareiplay.core.message_queue import MessageQueue

    event, _command_manager, _drainer = _screen_chat_window(chat_window, monkeypatch)
    queue = MessageQueue.instance()

    _scan(event, "souler[Alice]说：$info")
    assert [m.silent for m in _run(queue.get_all_messages()).values()] == [False]

    _run(queue.clear_queue())
    with command_silence(True):
        _scan(event, "souler[Bob]说：$info")

    assert [m.silent for m in _run(queue.get_all_messages()).values()] == [True]


def test_monitoring_loop_executes_a_screen_command_on_the_tick_after_it_is_scanned(
    monkeypatch,
):
    """D8: the loop drains before it scans, so a queued screen command waits one tick.

    This is the accepted cost of routing real-time commands through the runtime
    queue. Because `start_monitoring` drains *before* it scans and then sleeps a
    second, a command seen on screen during scan N is not executed until the drain
    of tick N+1 — one full `asyncio.sleep(1)` of added feedback latency in a live
    room. The test counts the sleeps that elapse between the scan which queued the
    command and the drain which executed it, so reordering the loop (which would
    drop the latency to zero) cannot happen unnoticed.
    """
    import asyncio
    from queue import Queue
    from types import SimpleNamespace

    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.models.message_info import MessageInfo
    from tests.test_app_controller_driver_subscribers import (
        FakeLogger,
        controller_without_init,
    )

    controller = controller_without_init()
    controller.config = {"commands": []}
    controller.input_queue = Queue()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *_args, **_kwargs: None,
        logger=SimpleNamespace(critical=lambda *_args, **_kwargs: None),
    )
    controller.logger = FakeLogger()
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)
    controller.timer_manager = SimpleNamespace(is_running=lambda: True, start=_noop)
    controller._drain_agent_command_spool = lambda: None
    controller.is_running = True
    controller.in_console_mode = False
    controller._update_status_from_screen = _noop

    asyncio.run(MessageQueue.instance().clear_queue())

    executed = []
    sleeps = {"count": 0}
    sleeps_before_execution = []
    scans = {"count": 0}

    async def execute_runtime_queue_messages(messages, send_screen_message=None):
        messages = list(messages)
        executed.extend(m.content for m in messages)
        return len(messages)

    drainer = RuntimeQueueDrainer(
        handler=controller.soul_handler,
        command_manager=SimpleNamespace(
            execute_runtime_queue_messages=execute_runtime_queue_messages
        ),
        send_screen_message=lambda *_args, **_kwargs: None,
    )

    async def drain():
        drained, command_count = await drainer.drain()
        if command_count:
            sleeps_before_execution.append(sleeps["count"])
        return drained, command_count

    async def process_current_screen():
        scans["count"] += 1
        if scans["count"] == 1:
            # The scan sees the command and `dispatch_intake` queues it.
            await MessageQueue.instance().put_message(
                MessageInfo(content="$info", nickname="Alice")
            )
        elif scans["count"] >= 3:
            controller.is_running = False
        return {"page_source": "", "screen": {}, "triggered_count": 0}

    controller.event_manager = SimpleNamespace(process_current_screen=process_current_screen)
    controller.runtime_input = SimpleNamespace(drain=_noop, paused=False)
    controller._runtime_queue_drainer = SimpleNamespace(drain=drain)

    async def noop_sleep(*_args, **_kwargs):
        sleeps["count"] += 1
        return None

    monkeypatch.setattr("ushareiplay.core.app_controller.asyncio.sleep", noop_sleep)
    monkeypatch.setattr(AppController, "_init_handlers", lambda _self: None)
    monkeypatch.setattr(
        "ushareiplay.managers.keyword_manager.KeywordManager.instance",
        lambda: SimpleNamespace(load_keywords_from_config=_noop),
    )

    asyncio.run(controller.start_monitoring())

    assert executed == ["$info"]
    # A whole loop tick (and its sleep) separates the scan from the execution.
    assert sleeps_before_execution == [1]
    assert scans["count"] == 3


def test_queued_screen_command_traverses_the_same_guard_bearing_path_as_a_backfilled_one(
    chat_window, monkeypatch
):
    """Both sources reach `process_command` under the same playback-muting guard.

    Role checks, permission level, the sleep guard and the guest-room guard all
    live in `process_command` (`command_manager.py`), which is wrapped by
    `playback_muting_guard`. Before #398 both sources already converged there, but
    real-time commands reached it inline and unsynchronised; this pins that a
    queued screen command is guarded exactly like a backfilled one.
    """
    from contextlib import contextmanager

    from ushareiplay.managers.command_manager import CommandManager

    guarded = []
    entered = []

    real_manager = CommandManager.__new__(CommandManager)
    real_manager.__init__()
    real_manager._logger = logging.getLogger("test_screen_guards")
    real_manager._handler = SimpleNamespace(config={"system_users": ["Console"]})
    real_manager.initialize_parser(
        [{"prefix": "play", "level": 1, "response_template": "{song}", "error_template": "{error}"}]
    )
    monkeypatch.setattr(real_manager, "get_command", lambda _cmd: SimpleNamespace(playback_muting=True))

    # `message_dispatch` is a read-only property, so the outbound seam is swapped
    # at the singleton seam. It is not what this test is about; keep it inert.
    def _inert_dispatch():
        dispatch = SimpleNamespace(
            send_screen_message=lambda *_a, **_k: None,
            send_for_message_info=lambda *_a, **_k: None,
        )
        dispatch.bind_handler = lambda _handler: dispatch
        return dispatch

    monkeypatch.setattr(
        "ushareiplay.managers.command_manager.MessageDispatch.instance",
        _inert_dispatch,
    )

    @contextmanager
    def _recording_guard(_command, _command_info):
        guarded.append(True)
        yield

    monkeypatch.setattr(real_manager, "playback_muting_guard", _recording_guard)

    async def _process_command(_command, message_info, _command_info):
        entered.append(message_info.content)
        return None

    monkeypatch.setattr(real_manager, "process_command", _process_command)

    event, _fake, drainer = _screen_chat_window(chat_window, monkeypatch)
    drainer.command_manager = real_manager

    _scan(event, "souler[Alice]说：$play 1")
    _run(chat_window.manager.dispatch_intake(["souler[Bob]说：$play 2"], room_owner="群主", from_backfill=True))

    _run(drainer.drain())

    # Both commands executed, in order, each inside the muting guard.
    assert entered == ["$play 1", "$play 2"]
    assert len(guarded) == 2


async def _noop(*_args, **_kwargs):
    return None


def test_process_missed_messages_accepts_dollar_prefix_and_queues_command():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_missed")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

        def scroll_container_until_element(self, *_args, **_kwargs):
            return (
                "message_content",
                object(),
                ["souler[Bob]说：$play later", "souler[Bob]说：:timer list"],
            )

        def send_message(self, _message):
            return None

    manager = MessageManager.instance()
    manager._handler = _with_ui_components(_FakeSoulHandler())
    manager._chat_logger = logging.getLogger("test_chat_logger_missed")
    manager._recovery_manager = None
    manager.observe(["souler[Anchor]说：:noop"])

    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    command_set = _run(manager.process_missed_messages())

    queued_messages = list(_run(queue.get_all_messages()).values())

    assert command_set is not None
    assert "$play later" in command_set
    assert any(m.content == "$play later" and m.nickname == "Bob" for m in queued_messages)


def test_process_missed_messages_sends_empty_message_after_finding_anchor():
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_missed_anchor")
            self.sent_messages = []

        def switch_to_app(self):
            return True

        def scroll_container_until_element(self, *_args, **_kwargs):
            return "message_content", object(), ["兴趣主题已更换为「Turn Around」"]

        def send_message(self, message):
            self.sent_messages.append(message)

    handler = _with_ui_components(_FakeSoulHandler())
    manager = MessageManager.instance()
    manager._handler = handler
    manager._chat_logger = logging.getLogger("test_chat_logger_missed_anchor")
    manager._recovery_manager = None
    manager.observe(["兴趣主题已更换为「Turn Around」"])

    assert _run(manager.process_missed_messages()) == set()
    # send_message("") should be called to scroll back to bottom
    assert handler.sent_messages == [""]


def test_missed_detection_fallback_prevents_false_missed():
    """屏幕上的行比窗口宽时，前向对齐会整体失配 —— 但锚点还在屏幕上，不算漏。

    这条用例原先把生产算法抄了一份来验证；现在走 observe() 的接口。
    """
    from ushareiplay.managers.message_manager import MessageManager

    manager = MessageManager.instance()
    # 窗口只保留 3 行，屏幕上有 5 行
    manager.observe(["msg_C", "msg_D", "msg_E"])

    delta = manager.observe(["msg_A", "msg_B", "msg_C", "msg_D", "msg_E"])

    assert delta.anchor == "msg_E"
    assert delta.missed is False
    # 锚点之后没有新行
    assert delta.new_lines == ()


def test_observe_reports_missed_when_the_anchor_scrolled_away():
    """锚点确实不在屏幕上时才是真的漏了。"""
    from ushareiplay.managers.message_manager import MessageManager

    manager = MessageManager.instance()
    manager.observe(["msg_A", "msg_B", "msg_C"])

    delta = manager.observe(["msg_X", "msg_Y", "msg_Z"])

    assert delta.missed is True
    assert delta.new_lines == ("msg_X", "msg_Y", "msg_Z")


def test_observe_returns_only_the_lines_after_the_anchor():
    from ushareiplay.managers.message_manager import MessageManager

    manager = MessageManager.instance()
    manager.observe(["msg_A", "msg_B", "msg_C"])

    delta = manager.observe(["msg_A", "msg_B", "msg_C", "msg_D"])

    assert delta.missed is False
    assert delta.new_lines == ("msg_D",)


def test_a_static_screen_is_never_reported_as_new_again():
    """同屏反复观察都不得再报新行。

    窗口提交的是增量而不是整屏：静屏（增量空）时窗口若被增量覆盖就等于被清空，
    下一次观察看不到锚点，整屏会被当成新增重新派发 —— 礼物重复道谢、热力值
    重复写库、命令重复执行。旧的 diff 算法 append 的是整屏，窗口跨静屏保留。
    """
    from ushareiplay.managers.message_manager import MessageManager

    manager = MessageManager.instance()
    screen = ["souler[A]说: 你好", "souler[A]送给Joyer", "souler[B]说: :play 稻香"]

    assert manager.observe(screen).new_lines == tuple(screen)
    for _ in range(3):
        delta = manager.observe(list(screen))
        assert delta.new_lines == ()
        assert delta.missed is False


def test_an_unreadable_screen_does_not_forget_the_window():
    """屏幕上什么都读不到（元素缺失/界面切换）时，窗口不能被清空。"""
    from ushareiplay.managers.message_manager import MessageManager

    manager = MessageManager.instance()
    manager.observe(["msg_A", "msg_B", "msg_C"])
    manager.observe([])

    # 只是多了一行，不该把整屏当成新增
    assert manager.observe(["msg_A", "msg_B", "msg_C", "msg_D"]).new_lines == ("msg_D",)


def _screen_chat_window(chat_window, monkeypatch):
    """A chat window whose event path feeds a recording command manager.

    Reuses the `chat_window` test bench (real `MessageManager`, fake handler and
    chat logger) and points the event at a `_FakeCommandManager` recording what
    execution actually received. Returns `(event, command_manager, drainer)`.
    """
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.runtime_services import RuntimeQueueDrainer
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager

    handler = chat_window.handler
    handler.key_actions = SimpleNamespace(switch_to_app=lambda: True)

    command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: command_manager))

    drainer = RuntimeQueueDrainer(
        handler=handler,
        command_manager=command_manager,
        send_screen_message=lambda *_args, **_kwargs: None,
        logger=handler.logger,
    )

    _run(MessageQueue.instance().clear_queue())
    return MessageContentEvent(handler), command_manager, drainer


def _scan(event, *rows):
    """Run the real screen-scan event over `rows`, as the monitoring loop does."""
    return _run(event.handle("message_content", [_FakeWrapper(row) for row in rows]))


def test_screen_chat_command_is_queued_and_not_executed_inline(chat_window, monkeypatch):
    """A real-time screen command joins the runtime queue instead of running there.

    Before #398 the scan called `execute_chat_scan` and executed immediately, so
    screen commands never crossed `MessageQueue` at all.
    """
    from ushareiplay.core.message_queue import MessageQueue

    event, command_manager, _drainer = _screen_chat_window(chat_window, monkeypatch)

    _scan(event, "souler[Outlier]说：$info")

    queued = list(_run(MessageQueue.instance().get_all_messages()).values())
    assert [m.content for m in queued] == ["$info"]
    assert [m.nickname for m in queued] == ["Outlier"]
    assert command_manager.received == []


def test_queued_screen_chat_command_is_executed_by_the_single_runtime_drainer(
    chat_window, monkeypatch
):
    """The same command is drained and executed by `RuntimeQueueDrainer`."""
    event, command_manager, drainer = _screen_chat_window(chat_window, monkeypatch)

    _scan(event, "souler[Outlier]说：$info")

    drained, command_count = _run(drainer.drain())

    assert drained == 1
    assert command_count == 1
    assert [m.content for m in command_manager.received] == ["$info"]
    assert [m.nickname for m in command_manager.received] == ["Outlier"]


def test_screen_and_backfilled_commands_share_one_draining_pipeline(chat_window, monkeypatch):
    """Both sources travel the same queue and drain in a single pass, with no drops.

    `from_backfill=True` is the historical path #396 already routed through the
    queue; the real-time scan now joins it instead of executing inline.
    """
    event, command_manager, drainer = _screen_chat_window(chat_window, monkeypatch)

    _scan(event, "souler[Alice]说：/play 1")
    _run(
        chat_window.manager.dispatch_intake(
            ["souler[Bob]说：/play 2"], room_owner="群主", from_backfill=True
        )
    )

    assert command_manager.received == []  # neither source executed on the way in

    drained, command_count = _run(drainer.drain())

    assert (drained, command_count) == (2, 2)
    assert [m.content for m in command_manager.received] == ["/play 1", "/play 2"]
    assert [m.nickname for m in command_manager.received] == ["Alice", "Bob"]

    # The queue is empty afterwards: nothing was left behind.
    assert _run(drainer.drain()) == (0, 0)


def test_message_content_event_feeds_the_runtime_queue_and_leaves_execution_to_the_drainer(
    chat_window, monkeypatch
):
    """The event's job is to feed the queue; the drainer's job is to execute.

    #398 inverted this test's original premise. The event used to execute screen
    commands itself and never touched `MessageQueue`; now it appends to the queue
    and leaves execution to `RuntimeQueueDrainer`. Work already in the queue when
    the screen is scanned is still carried over untouched, not consumed here.
    """
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.models.message_info import MessageInfo

    event, command_manager, drainer = _screen_chat_window(chat_window, monkeypatch)
    queue = MessageQueue.instance()
    _run(queue.put_message(MessageInfo(content=":timer list", nickname="Timer")))

    _scan(event, "souler[Outlier]说：$info")

    # Fed, not consumed: the event neither drained nor executed anything.
    assert queue.get_queue_size() == 2
    assert command_manager.received == []

    drained, command_count = _run(drainer.drain())

    assert (drained, command_count) == (2, 2)
    assert [m.content for m in command_manager.received] == [":timer list", "$info"]


def test_message_content_event_queues_dollar_command_for_the_runtime_queue(chat_window, monkeypatch):
    """The event hands the command to the runtime queue instead of executing it (#398)."""
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager

    fake_command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: fake_command_manager))
    chat_window.handler.key_actions = SimpleNamespace(switch_to_app=lambda: True)
    queue = MessageQueue.instance()
    _run(queue.clear_queue())

    event = MessageContentEvent(chat_window.handler)
    _run(event.handle("message_content", [_FakeWrapper("souler[Outlier]说：$info")]))

    assert fake_command_manager.received == []
    assert [m.content for m in _run(queue.get_all_messages()).values()] == ["$info"]
