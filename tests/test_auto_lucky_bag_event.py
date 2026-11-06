from unittest.mock import MagicMock
import pytest
from ushareiplay.core.config_view import ConfigSectionView
from ushareiplay.events.lucky_bag_entry import LuckyBagEntryEvent
from ushareiplay.managers.event_manager import EventManager


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.current_time = start

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float):
        self.current_time += seconds


class DummyElement:
    def __init__(self, key: str):
        self.key = key
        self.clicked = False

    def click(self):
        self.clicked = True


def make_dummy_handler(config_data=None):
    handler = MagicMock()
    config = ConfigSectionView("soul", config_data or {
        "package_name": "cn.soulapp.android",
        "lucky_bag": {
            "enabled": True,
            "countdown_seconds": 10.0,
            "claim_timeout": 3.0,
        },
        "elements": {
            "lucky_bag_entry": '//android.widget.FrameLayout[@resource-id="cn.soulapp.android:id/countDownLuckyBagView"]',
            "lucky_bag_claim_operation": '//android.widget.TextView[@resource-id="cn.soulapp.android:id/tvOperation"]',
            "lucky_bag_claim_open": '//android.widget.TextView[@resource-id="cn.soulapp.android:id/tvOpenFortuneBag"]',
        }
    })
    handler.config = config
    handler.logger = MagicMock()
    handler.element_finder = MagicMock()
    handler.key_actions = MagicMock()
    handler.controller = MagicMock()
    handler.driver.current_package = "cn.soulapp.android"
    return handler


@pytest.mark.asyncio
async def test_lucky_bag_initial_detection_starts_countdown():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    event = LuckyBagEntryEvent(handler, clock=clock)

    assert event.state == LuckyBagEntryEvent.STATE_IDLE
    result = await event.handle("lucky_bag_entry", MagicMock())

    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN
    assert event._countdown_target_time == 1010.0
    handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_countdown_ticks_do_not_block_and_do_not_click():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    event = LuckyBagEntryEvent(handler, clock=clock)

    await event.handle("lucky_bag_entry", MagicMock())
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN

    # Advance 5 seconds (still < 10)
    clock.advance(5.0)
    result = await event.handle("lucky_bag_entry", MagicMock())
    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN
    handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_disappears_during_countdown_resets_to_idle():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    event = LuckyBagEntryEvent(handler, clock=clock)

    await event.handle("lucky_bag_entry", MagicMock())
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN

    # Element absent before countdown ends
    await event.on_element_absent("lucky_bag_entry")
    assert event.state == LuckyBagEntryEvent.STATE_IDLE


@pytest.mark.asyncio
async def test_lucky_bag_countdown_completed_ui_busy_defers():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    runtime = MagicMock()
    runtime.is_ui_busy.return_value = True

    event = LuckyBagEntryEvent(handler, runtime=runtime, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    # Advance 10s
    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())
    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN
    handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_countdown_completed_defers_when_soul_not_foreground():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    handler.driver.current_package = "com.sec.android.app.launcher"

    event = LuckyBagEntryEvent(handler, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    # Advance 10s
    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())
    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN
    handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_claim_success_with_operation_button():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    entry_btn = DummyElement("lucky_bag_entry")
    op_btn = DummyElement("lucky_bag_claim_operation")

    handler.element_finder.wait_for_element_clickable.return_value = entry_btn
    handler.element_finder.wait_for_any_element.return_value = ("lucky_bag_claim_operation", op_btn)

    event = LuckyBagEntryEvent(handler, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    # Advance to end of countdown
    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())

    assert result is True
    assert entry_btn.clicked is True
    assert op_btn.clicked is True
    assert event.state == LuckyBagEntryEvent.STATE_CLAIMED


@pytest.mark.asyncio
async def test_lucky_bag_claim_success_with_open_fortune_button():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    entry_btn = DummyElement("lucky_bag_entry")
    open_btn = DummyElement("lucky_bag_claim_open")

    handler.element_finder.wait_for_element_clickable.return_value = entry_btn
    handler.element_finder.wait_for_any_element.return_value = ("lucky_bag_claim_open", open_btn)

    event = LuckyBagEntryEvent(handler, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())

    assert result is True
    assert entry_btn.clicked is True
    assert open_btn.clicked is True
    assert event.state == LuckyBagEntryEvent.STATE_CLAIMED


@pytest.mark.asyncio
async def test_lucky_bag_claim_timeout_presses_back():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    entry_btn = DummyElement("lucky_bag_entry")

    handler.element_finder.wait_for_element_clickable.return_value = entry_btn
    handler.element_finder.wait_for_any_element.return_value = (None, None)

    event = LuckyBagEntryEvent(handler, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())

    assert result is False
    assert entry_btn.clicked is True
    handler.key_actions.press_back.assert_called_once()
    assert event.state == LuckyBagEntryEvent.STATE_CLAIMED


@pytest.mark.asyncio
async def test_lucky_bag_claim_timeout_skips_back_when_soul_left_foreground():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    entry_btn = DummyElement("lucky_bag_entry")

    handler.element_finder.wait_for_element_clickable.return_value = entry_btn
    def mock_wait_any(keys, timeout=None):
        handler.driver.current_package = "com.tencent.mobileqq"
        return None, None

    handler.element_finder.wait_for_any_element.side_effect = mock_wait_any

    event = LuckyBagEntryEvent(handler, clock=clock)
    await event.handle("lucky_bag_entry", MagicMock())

    clock.advance(10.0)
    result = await event.handle("lucky_bag_entry", MagicMock())

    assert result is False
    assert entry_btn.clicked is True
    handler.key_actions.press_back.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_claimed_state_suppresses_repeat_clicks():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    event = LuckyBagEntryEvent(handler, clock=clock)
    event.state = LuckyBagEntryEvent.STATE_CLAIMED

    # While still in page_source
    result = await event.handle("lucky_bag_entry", MagicMock())
    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_CLAIMED
    handler.element_finder.wait_for_element_clickable.assert_not_called()


@pytest.mark.asyncio
async def test_lucky_bag_claimed_resets_to_idle_on_absence():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler()
    event = LuckyBagEntryEvent(handler, clock=clock)
    event.state = LuckyBagEntryEvent.STATE_CLAIMED

    # Button disappears from page_source
    await event.on_element_absent("lucky_bag_entry")
    assert event.state == LuckyBagEntryEvent.STATE_IDLE

    # Now when button appears again, it starts a fresh countdown
    await event.handle("lucky_bag_entry", MagicMock())
    assert event.state == LuckyBagEntryEvent.STATE_COUNTDOWN
    assert event._countdown_target_time == 1010.0


@pytest.mark.asyncio
async def test_lucky_bag_disabled_in_config():
    clock = FakeClock(1000.0)
    handler = make_dummy_handler({
        "lucky_bag": {"enabled": False},
        "elements": {"lucky_bag_entry": "cn.soulapp.android:id/countDownLuckyBagView"}
    })
    event = LuckyBagEntryEvent(handler, clock=clock)

    result = await event.handle("lucky_bag_entry", MagicMock())
    assert result is False
    assert event.state == LuckyBagEntryEvent.STATE_IDLE


@pytest.mark.asyncio
async def test_event_manager_integration_with_lucky_bag():
    handler = make_dummy_handler()
    manager = EventManager.__new__(EventManager)
    manager.__init__(handler=handler)
    runtime = MagicMock()
    runtime.is_ui_busy.return_value = False
    runtime.is_paused.return_value = False
    manager.configure_runtime(runtime)
    manager.initialize_events()

    # Verify event loaded and bound
    assert "lucky_bag_entry" in manager.element_to_event
    event_module = manager.event_modules.get(manager.element_to_event["lucky_bag_entry"])
    assert event_module is not None
    lucky_event = event_module.event
    assert lucky_event.__class__.__name__ == "LuckyBagEntryEvent"

    # Page source with lucky bag
    page_with_bag = """
    <hierarchy>
      <android.widget.FrameLayout package="cn.soulapp.android" resource-id="cn.soulapp.android:id/countDownLuckyBagView" />
    </hierarchy>
    """
    page_without_bag = """
    <hierarchy>
      <android.widget.TextView package="cn.soulapp.android" text="hello" />
    </hierarchy>
    """

    # 1. First sight: starts countdown
    outcome = await manager.react_to_page(page_with_bag)
    assert outcome["triggered_count"] == 1
    assert lucky_event.state == LuckyBagEntryEvent.STATE_COUNTDOWN

    # 2. Bag disappears: on_element_absent resets to IDLE
    outcome2 = await manager.react_to_page(page_without_bag)
    assert lucky_event.state == LuckyBagEntryEvent.STATE_IDLE
