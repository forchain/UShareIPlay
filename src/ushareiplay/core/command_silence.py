from contextlib import contextmanager
from contextvars import ContextVar


_silent_depth: ContextVar[int] = ContextVar("command_silent_depth", default=0)


def is_command_silent() -> bool:
    return _silent_depth.get() > 0


@contextmanager
def command_silence(enabled: bool):
    if not enabled:
        yield
        return

    token = _silent_depth.set(_silent_depth.get() + 1)
    try:
        yield
    finally:
        _silent_depth.reset(token)
