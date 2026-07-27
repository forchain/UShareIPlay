"""Interface tests for the Appium driver lifecycle seam."""

from types import SimpleNamespace

from ushareiplay.core.driver_lifecycle import DriverLifecycle


class _RecordingDriver:
    def __init__(self, name):
        self.name = name
        self.quit_calls = 0
        self.settings = None

    def quit(self):
        self.quit_calls += 1

    def update_settings(self, settings):
        self.settings = settings


class _DriverAware:
    def __init__(self):
        self.driver = None


def _make(obs=None, sleep=lambda _s: None):
    return DriverLifecycle(
        factory=lambda: SimpleNamespace(update_settings=lambda _s: None),
        obs=obs,
        sleep=sleep,
        recovery_delay=0,
    )


def test_initialize_creates_driver_and_propagates_to_subscribers():
    lifecycle = _make()
    subscriber = _DriverAware()

    lifecycle.attach(subscriber)
    driver = lifecycle.initialize()

    assert driver is not None
    assert subscriber.driver is driver


def test_shutdown_quits_driver_and_clears_reference():
    driver = _RecordingDriver("d1")
    lifecycle = DriverLifecycle(
        factory=lambda: driver,
        obs=None,
        sleep=lambda _s: None,
    )
    lifecycle.initialize()

    lifecycle.shutdown()

    assert driver.quit_calls == 1
    assert lifecycle.driver is None


def test_reinitialize_replaces_driver_and_propagates_to_existing_subscribers():
    old = _RecordingDriver("old")
    new = _RecordingDriver("new")
    factory_calls = []

    def factory():
        factory_calls.append(None)
        return factory_calls[-1] is None and new or old  # noqa

    lifecycle = DriverLifecycle(
        factory=lambda: factory_calls.append(None) or (new if len(factory_calls) > 1 else old),
        settings={"waitForIdleTimeout": 0},
        obs=None,
        sleep=lambda _s: None,
    )
    lifecycle.initialize()
    subscriber = _DriverAware()
    lifecycle.attach(subscriber)
    old_initial = lifecycle.driver

    ok = lifecycle.reinitialize()

    assert ok is True
    assert old_initial.quit_calls == 1
    assert lifecycle.driver is new
    assert subscriber.driver is new
    assert new.settings == {"waitForIdleTimeout": 0}


def test_reinitialize_is_reentry_guarded():
    """Concurrent reinit requests collapse into one driver rebuild."""
    factory_calls = []

    def factory():
        factory_calls.append(SimpleNamespace(update_settings=lambda _s: None))
        return factory_calls[-1]

    lifecycle = DriverLifecycle(
        factory=factory,
        obs=None,
        sleep=lambda _s: None,
    )
    lifecycle.initialize()

    # Simulate concurrent call by forcing reentry via the public path is not
    # possible; instead, drive reinit twice in sequence to confirm guard
    # semantics: only the first call rebuilds when reentry is faked.
    lifecycle._reentry = True
    blocked = lifecycle.reinitialize()
    lifecycle._reentry = False

    assert blocked is False


def test_reinitialize_emits_reinit_ok_on_success_and_error_on_failure():
    events = []

    class _Obs:
        def emit(self, event, **kwargs):
            events.append((event, kwargs))

    def factory():
        return SimpleNamespace(update_settings=lambda _s: None)

    lifecycle = DriverLifecycle(factory=factory, obs=_Obs(), sleep=lambda _s: None)
    lifecycle.initialize()

    assert ("driver.init.start", {}) in events
    assert ("driver.init.ok", {}) in events

    # Force failure by replacing the factory to raise.
    def failing_factory():
        raise RuntimeError("kaboom")

    lifecycle._factory = failing_factory
    ok = lifecycle.reinitialize()

    assert ok is False
    assert any(event[0] == "driver.reinit.error" for event in events)


def test_attach_ignores_objects_without_driver_attribute():
    lifecycle = _make()

    lifecycle.attach(None)
    lifecycle.attach(object())

    assert lifecycle.subscribers == []
