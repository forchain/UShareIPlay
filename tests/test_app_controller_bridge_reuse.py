"""The driver factory must never reuse a bridge pointed at a different Appium host."""
from unittest.mock import patch

from ushareiplay.core.app_controller import AppController


class FakeBridge:
    def __init__(self, target_host, target_port, bridge_port=41234):
        self.target_host = target_host
        self.target_port = int(target_port)
        self.bridge_host = "127.0.0.1"
        self.bridge_port = bridge_port
        self.is_running = True
        self.stop_called = False

    def stop(self):
        self.stop_called = True
        self.is_running = False


class FakeDriver:
    def __init__(self):
        self.updated_settings = []

    def update_settings(self, settings):
        self.updated_settings.append(settings)


def _controller(appium_host, appium_port):
    controller = AppController.__new__(AppController)
    controller.config = {
        "device": {
            "platform_name": "Android",
            "platform_version": "13",
            "name": "pixel",
            "automation_name": "UiAutomator2",
            "no_reset": True,
        },
        "soul": {"package_name": "cn.soulapp.android", "chat_activity": ".MainActivity"},
        "appium": {"host": appium_host, "port": appium_port},
    }
    controller.logger = None
    controller._network_bridge = None
    return controller


def _patch_driver_remote(monkeypatch):
    captured = {}

    def fake_remote(command_executor, options=None):
        captured["url"] = command_executor
        return FakeDriver()

    monkeypatch.setattr(
        "ushareiplay.core.app_controller.webdriver.Remote", fake_remote
    )
    monkeypatch.delenv("APPIUM_HOST", raising=False)
    monkeypatch.delenv("APPIUM_PORT", raising=False)
    return captured


def test_init_driver_reuses_bridge_when_target_matches(monkeypatch):
    controller = _controller("192.168.8.103", 4723)
    bridge = FakeBridge("192.168.8.103", 4723, bridge_port=41234)
    controller._network_bridge = bridge
    captured = _patch_driver_remote(monkeypatch)

    with patch("ushareiplay.core.network_bridge.ensure_appium_endpoint") as mock_ensure:
        controller._init_driver()

    mock_ensure.assert_not_called()
    assert bridge.stop_called is False
    assert captured["url"] == "http://127.0.0.1:41234"


def test_init_driver_discards_bridge_pointing_at_another_host(monkeypatch):
    controller = _controller("192.168.8.108", 4723)
    stale = FakeBridge("192.168.8.103", 4723, bridge_port=41234)
    controller._network_bridge = stale
    captured = _patch_driver_remote(monkeypatch)

    fresh = FakeBridge("192.168.8.108", 4723, bridge_port=43999)
    with patch(
        "ushareiplay.core.network_bridge.ensure_appium_endpoint",
        return_value=("127.0.0.1", 43999, fresh),
    ) as mock_ensure:
        controller._init_driver()

    mock_ensure.assert_called_once()
    assert stale.stop_called is True
    assert controller._network_bridge is fresh
    assert captured["url"] == "http://127.0.0.1:43999"


def test_init_driver_discards_bridge_pointing_at_another_port(monkeypatch):
    controller = _controller("192.168.8.103", 4724)
    stale = FakeBridge("192.168.8.103", 4723, bridge_port=41234)
    controller._network_bridge = stale
    captured = _patch_driver_remote(monkeypatch)

    fresh = FakeBridge("192.168.8.103", 4724, bridge_port=43999)
    with patch(
        "ushareiplay.core.network_bridge.ensure_appium_endpoint",
        return_value=("127.0.0.1", 43999, fresh),
    ):
        controller._init_driver()

    assert stale.stop_called is True
    assert captured["url"] == "http://127.0.0.1:43999"
