from types import SimpleNamespace

import pytest

from ushareiplay.core.command_silence import command_silence
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.models.message_info import MessageInfo


class _Runtime:
    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class _Handler:
    def __init__(self):
        self.sent = []
        self.logger = SimpleNamespace(
            info=lambda _message: None,
            warning=lambda _message: None,
            error=lambda _message: None,
        )

    def send_message(self, message):
        self.sent.append(message)


class _UserManager:
    def __init__(self):
        self.sent = []

    def send_private_message_to_user(self, nickname, message):
        self.sent.append((nickname, message))
        return True


@pytest.fixture(autouse=True)
def reset_message_dispatch_singleton():
    MessageDispatch.reset_instance()
    yield
    MessageDispatch.reset_instance()


def _make_dispatch():
    dispatch = MessageDispatch.initialize()
    dispatch._handler = _Handler()
    dispatch._user_manager = _UserManager()
    runtime = _Runtime()
    dispatch.configure_runtime(runtime)
    return dispatch, runtime


def test_send_screen_message_routes_and_emits_result():
    dispatch, runtime = _make_dispatch()

    dispatch.send_screen_message("hello")

    assert dispatch.handler.sent == ["hello"]
    assert runtime.events == [
        ("message.dispatch.screen", {"ctx": {"message_len": 5, "sent": True}})
    ]


def test_send_screen_message_suppresses_explicit_or_context_silence():
    dispatch, runtime = _make_dispatch()

    dispatch.send_screen_message("explicit", silent=True)
    with command_silence(True):
        dispatch.send_screen_message("context")

    assert dispatch.handler.sent == []
    assert runtime.events == [
        ("message.dispatch.suppressed", {"ctx": {"channel": "screen", "message_len": 8}}),
        ("message.dispatch.suppressed", {"ctx": {"channel": "screen", "message_len": 7}}),
    ]


def test_send_screen_message_emits_failure_before_reraising_ui_error():
    dispatch, runtime = _make_dispatch()

    def raise_ui_error(_message):
        raise RuntimeError("UI unavailable")

    dispatch.handler.send_message = raise_ui_error

    with pytest.raises(RuntimeError, match="UI unavailable"):
        dispatch.send_screen_message("hello")

    assert runtime.events == [
        ("message.dispatch.screen", {"ctx": {"message_len": 5, "sent": False}})
    ]


def test_private_and_message_info_routing_keep_private_replies_private():
    dispatch, runtime = _make_dispatch()

    assert dispatch.send_private_message("Alice", "private") is True
    assert dispatch.send_for_message_info(
        MessageInfo(content="$demo", nickname="Bob", private_reply=True),
        "reply",
        silent=True,
    ) is True
    dispatch.send_for_message_info(
        MessageInfo(content=":demo", nickname="Carol"), "public"
    )

    assert dispatch.user_manager.sent == [("Alice", "private"), ("Bob", "reply")]
    assert dispatch.handler.sent == ["public"]
    assert runtime.events == [
        (
            "message.dispatch.private",
            {"ctx": {"nickname": "Alice", "message_len": 7, "sent": True}},
        ),
        (
            "message.dispatch.private",
            {"ctx": {"nickname": "Bob", "message_len": 5, "sent": True}},
        ),
        ("message.dispatch.screen", {"ctx": {"message_len": 6, "sent": True}}),
    ]


def test_private_message_emits_failed_result_when_user_manager_returns_false():
    dispatch, runtime = _make_dispatch()
    dispatch.user_manager.send_private_message_to_user = lambda _nickname, _message: False

    assert dispatch.send_private_message("Alice", "private") is False
    assert runtime.events == [
        (
            "message.dispatch.private",
            {"ctx": {"nickname": "Alice", "message_len": 7, "sent": False}},
        )
    ]
