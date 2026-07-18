import asyncio
from types import SimpleNamespace

from ushareiplay.core.base_command import BaseCommand


class _Logger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class _SoulHandler:
    def __init__(self):
        self.logger = _Logger()
        self.mic_ensured = 0

    def ensure_mic_active(self):
        self.mic_ensured += 1

    def log_error(self, message):
        self.logger.error(message)


def _make_controller():
    return SimpleNamespace(soul_handler=_SoulHandler(), music_handler=object())


class _EchoCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        return {'message': ' '.join(parameters)}


class _MicCommand(BaseCommand):
    requires_mic = True

    async def do_process(self, message_info, parameters):
        return {'message': 'ok'}


class _BoomCommand(BaseCommand):
    error_message = '处理失败: {error}'

    async def do_process(self, message_info, parameters):
        raise RuntimeError('boom')


class _ContextCommand(BaseCommand):
    error_message = '{error}'

    def error_context(self, message_info, parameters):
        return {'party_id': parameters[0] if parameters else 'unknown'}

    async def do_process(self, message_info, parameters):
        raise RuntimeError('boom')


def test_process_calls_do_process_and_returns_result():
    command = _EchoCommand(_make_controller())
    result = asyncio.run(command.process(None, ['a', 'b']))
    assert result == {'message': 'a b'}


def test_process_runs_mic_prelude_only_when_required():
    plain_controller = _make_controller()
    plain = _EchoCommand(plain_controller)
    asyncio.run(plain.process(None, []))
    assert plain_controller.soul_handler.mic_ensured == 0

    mic_controller = _make_controller()
    mic = _MicCommand(mic_controller)
    result = asyncio.run(mic.process(None, []))
    assert result == {'message': 'ok'}
    assert mic_controller.soul_handler.mic_ensured == 1


def test_process_maps_exception_to_error_message_and_logs_traceback():
    controller = _make_controller()
    command = _BoomCommand(controller)

    result = asyncio.run(command.process(None, []))

    assert result == {'error': '处理失败: boom'}
    assert len(controller.soul_handler.logger.errors) == 1
    assert 'RuntimeError: boom' in controller.soul_handler.logger.errors[0]


def test_process_merges_error_context_into_error_result():
    command = _ContextCommand(_make_controller())

    result = asyncio.run(command.process(None, ['12345']))

    assert result == {'error': 'boom', 'party_id': '12345'}


def test_handler_attr_exposes_named_handler():
    controller = _make_controller()

    class _SoulAliased(BaseCommand):
        handler_attr = 'soul_handler'

        async def do_process(self, message_info, parameters):
            return {}

    command = _SoulAliased(controller)
    assert command.handler is controller.soul_handler

    plain = _EchoCommand(controller)
    assert plain.handler is None


def test_coerce_int_validates_and_range_checks():
    command = _EchoCommand(_make_controller())

    assert command.coerce_int('5', 1, 12, 'bad') == (5, None)
    assert command.coerce_int('abc', 1, 12, 'bad') == (None, 'bad')
    assert command.coerce_int('0', 1, 12, 'bad') == (None, 'bad')
    assert command.coerce_int('13', 1, 12, 'bad') == (None, 'bad')
    assert command.coerce_int('7') == (7, None)
