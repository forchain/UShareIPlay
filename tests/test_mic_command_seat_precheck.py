"""Ticket #317: `:mic` 的决定逻辑与委托。

`:mic` 现在只做两件事：决定目标状态，然后交给 `MicManager.set_active()`。
麦位前置检查、content-desc 状态读取与点击都在模块里 —— 机件测试见
tests/test_mic_manager.py（原先那份重复的机件测试已并入其中）。

`:mic 0` 从不上麦；不在麦位时裸 `:mic` 等同于开麦（抢麦会随座位自动开麦）。
"""

from types import SimpleNamespace

from ushareiplay.commands.mic import MicCommand


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _SoulHandler:
    """只提供 `:mic` 自己还要用到的两件事：麦位判断与日志。"""

    def __init__(self, on_seat=True):
        self.logger = _Logger()
        self._on_seat = on_seat

    def is_on_seat(self):
        return self._on_seat


class _MicManager:
    def __init__(self, state=False):
        self.state_value = state
        self.calls = []

    def state(self):
        return self.state_value

    def set_active(self, enable, *, report_noop=False):
        self.calls.append((enable, report_noop))
        return {"state": "1" if enable else "0"}


def _make_command(handler, mic_state=False):
    controller = SimpleNamespace(soul_handler=handler, music_handler=SimpleNamespace())
    command = MicCommand(controller)
    mic_manager = _MicManager(state=mic_state)
    command._mic_manager = mic_manager
    return command, mic_manager


def _run(command, parameters):
    import asyncio

    return asyncio.run(command.do_process(SimpleNamespace(nickname="Console"), parameters))


def test_mic_on_delegates_to_set_active_with_noop_reporting():
    handler = _SoulHandler(on_seat=True)
    command, mic_manager = _make_command(handler)

    result = _run(command, ["1"])

    assert mic_manager.calls == [(True, True)]
    assert result == {"state": "1"}


def test_mic_off_delegates_to_set_active_and_never_seats():
    handler = _SoulHandler(on_seat=False)
    command, mic_manager = _make_command(handler)

    result = _run(command, ["0"])

    assert mic_manager.calls == [(False, True)]
    assert result == {"state": "0"}


def test_bare_mic_from_off_seat_means_on_not_the_inverse():
    """抢麦会随座位自动开麦，因此不在麦位时裸 :mic 等同于开麦。"""
    handler = _SoulHandler(on_seat=False)
    command, mic_manager = _make_command(handler, mic_state=False)

    result = _run(command, [])

    assert mic_manager.calls == [(True, True)]
    assert result == {"state": "1"}


def test_bare_mic_when_seated_flips_the_current_state():
    handler = _SoulHandler(on_seat=True)
    command, mic_manager = _make_command(handler, mic_state=True)

    result = _run(command, [])

    assert mic_manager.calls == [(False, True)]
    assert result == {"state": "0"}


def test_bare_mic_when_seated_and_status_unreadable_reports_error():
    handler = _SoulHandler(on_seat=True)
    command, mic_manager = _make_command(handler, mic_state=None)

    result = _run(command, [])

    assert mic_manager.calls == []
    assert result == {"error": "Failed to get mic status"}


def test_invalid_parameter_is_rejected_without_touching_the_mic():
    handler = _SoulHandler(on_seat=True)
    command, mic_manager = _make_command(handler)

    result = _run(command, ["maybe"])

    assert mic_manager.calls == []
    assert "error" in result
