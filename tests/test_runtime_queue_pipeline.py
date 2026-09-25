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

    async def execute_chat_scan(self, rows):
        from ushareiplay.managers.command_manager import CommandManager

        manager = CommandManager.__new__(CommandManager)
        manager.__init__()
        manager.execute_command_messages = self.execute_command_messages
        return await manager.execute_chat_scan(rows)


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


def test_process_new_messages_accepts_dollar_prefix_and_keeps_content():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = MessageManager.instance()
        manager._handler = _with_ui_components(_FakeSoulHandler())
        manager._chat_logger = logging.getLogger("test_chat_logger_new")
        manager.observe(["souler[Alice]说：$play 123"])

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$play 123"]
        assert [m.content for m in fake_command_manager.received] == ["$play 123"]
        assert [m.nickname for m in fake_command_manager.received] == ["Alice"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_accepts_fullwidth_dollar_prefix_and_keeps_content():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new_fullwidth")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = MessageManager.instance()
        manager._handler = _with_ui_components(_FakeSoulHandler())
        manager._chat_logger = logging.getLogger("test_chat_logger_new_fullwidth")
        manager.observe(["souler[Alice]说：＄info"])

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["＄info"]
        assert [m.content for m in fake_command_manager.received] == ["＄info"]
        assert [m.nickname for m in fake_command_manager.received] == ["Alice"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_skips_non_command_and_keeps_following_dollar_command():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_new_mixed")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = MessageManager.instance()
        manager._handler = _with_ui_components(_FakeSoulHandler())
        manager._chat_logger = logging.getLogger("test_chat_logger_new_mixed")
        # 两句都是"新"的：第一句是普通发言，第二句是命令
        manager.observe(["souler[Alice]说：hello", "souler[Alice]说：$play 123"])

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$play 123"]
        assert [m.content for m in fake_command_manager.received] == ["$play 123"]
    finally:
        CommandManager.instance = original_cmd_instance


def test_process_new_messages_accepts_ascii_colon_in_chat_prefix():
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.message_manager import MessageManager

    class _FakeSoulHandler:
        def __init__(self):
            self.logger = logging.getLogger("test_message_manager_ascii_colon")
            self.config = {"logging": {"directory": "logs"}}

        def switch_to_app(self):
            return True

    original_cmd_instance = CommandManager.instance
    try:
        fake_command_manager = _FakeCommandManager()
        CommandManager.instance = classmethod(lambda cls: fake_command_manager)
        manager = MessageManager.instance()
        manager._handler = _with_ui_components(_FakeSoulHandler())
        manager._chat_logger = logging.getLogger("test_chat_logger_ascii_colon")
        manager.observe(["souler[Alice]说:$info"])

        messages = _run(manager.process_new_messages())

        assert [m.content for m in messages] == ["$info"]
        assert [m.content for m in fake_command_manager.received] == ["$info"]
    finally:
        CommandManager.instance = original_cmd_instance


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


def test_message_content_update_logic_does_not_drain_runtime_queue():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager
    from ushareiplay.managers.info_manager import InfoManager
    from ushareiplay.models.message_info import MessageInfo

    class _FakeCmdMgr:
        def update_commands(self):
            return None

    class _FakeInfoMgr:
        def update_playback_info_cache(self):
            return None

    original_cmd_instance = CommandManager.instance
    original_info_instance = InfoManager.instance
    CommandManager.instance = classmethod(lambda cls: _FakeCmdMgr())
    InfoManager.instance = classmethod(lambda cls: _FakeInfoMgr())
    try:
        queue = MessageQueue.instance()
        _run(queue.clear_queue())
        _run(queue.put_message(MessageInfo(content=":timer list", nickname="Timer")))

        handler = _FakeHandler()
        event = MessageContentEvent(handler)
        _run(event._process_update_logic())

        assert queue.get_queue_size() == 1
    finally:
        CommandManager.instance = original_cmd_instance
        InfoManager.instance = original_info_instance


def test_message_content_event_dispatches_dollar_command(chat_window, monkeypatch):
    """事件把命令交给 CommandManager 执行 —— 通过真实的 MessageManager 接口。"""
    from ushareiplay.events.message_content import MessageContentEvent
    from ushareiplay.managers.command_manager import CommandManager

    fake_command_manager = _FakeCommandManager()
    monkeypatch.setattr(CommandManager, "instance", classmethod(lambda cls: fake_command_manager))
    chat_window.handler.key_actions = SimpleNamespace(switch_to_app=lambda: True)

    event = MessageContentEvent(chat_window.handler)

    _run(event.handle("message_content", [_FakeWrapper("souler[Outlier]说：$info")]))

    assert [m.content for m in fake_command_manager.received] == ["$info"]
