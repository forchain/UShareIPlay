from selenium.common.exceptions import WebDriverException

from ushareiplay.core.driver_decorator import with_driver_recovery


class FakeObserver:
    def __init__(self):
        self.events = []

    def emit(self, event, **kwargs):
        self.events.append((event, kwargs))


class FakeRecoveryContext:
    def __init__(self, result=True):
        self.result = result
        self.reinitialize_calls = 0
        self.obs = FakeObserver()

    def reinitialize_driver(self):
        self.reinitialize_calls += 1
        return self.result

    def emit(self, event, **kwargs):
        self.obs.emit(event, **kwargs)


class NestedOwner:
    def __init__(self, context=None):
        self.driver_recovery_context = context


class DecoratedWorker:
    def __init__(self, owner, fail_once=False):
        self.owner = owner
        self.fail_once = fail_once
        self.calls = 0

    @with_driver_recovery(op="read")
    def read_value(self):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise WebDriverException("driver lost")
        return "ok"

    @with_driver_recovery(retry=False, op="write")
    def write_value(self):
        self.calls += 1
        raise WebDriverException("driver lost")


def test_read_operation_recovers_through_owner_context_and_retries():
    context = FakeRecoveryContext()
    owner = NestedOwner(context=context)
    worker = DecoratedWorker(owner=owner, fail_once=True)

    assert worker.read_value() == "ok"
    assert worker.calls == 2
    assert context.reinitialize_calls == 1
    assert [event for event, _ in context.obs.events] == [
        "recovery.reinitialized",
        "recovery.retry",
    ]


def test_write_operation_recovers_without_retry_when_retry_disabled():
    context = FakeRecoveryContext()
    owner = NestedOwner(context=context)
    worker = DecoratedWorker(owner=owner)

    assert worker.write_value() is None
    assert worker.calls == 1
    assert context.reinitialize_calls == 1
    assert [event for event, _ in context.obs.events] == [
        "recovery.reinitialized",
        "recovery.no_retry",
    ]


def test_owner_without_driver_recovery_context_returns_none():
    worker = DecoratedWorker(owner=NestedOwner(), fail_once=True)

    assert worker.read_value() is None
    assert worker.calls == 1
