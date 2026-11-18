"""接线层收口（票 #556）：组合根构造六角形座位用例与 Appium 驱动，旧单例包已删除。

本文件钉住三件事：
1. 旧 `managers/seat_manager` 包及旧属性已从 `AppController` 彻底删除；
2. 观测器与座位服务共用同一份 `SeatPanelDriver` / `SeatPanelReader`；
3. 真实启动路径跑得通（`_init_handlers()` -> 排空运行时队列 -> `prepare_for_chat_scan`）。
"""

import importlib
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from ushareiplay.adapters.outbound.appium.soul.seat_panel_driver import SeatPanelDriver
from ushareiplay.bootstrap.container import AppContainer
from ushareiplay.modules.shared.message_info import MessageInfo
from ushareiplay.modules.seat.use_cases import SeatObservationService, SeatService

RETIRED_SEAT_MODULES = ("seat_ui", "seat_check", "seating", "reservation", "subsystem", "seat_observation")

RETIRED_CONTROLLER_ATTRS = (
    "seat_ui_manager",
    "seat_check_manager",
    "reservation_manager",
    "seating_manager",
    "seat_manager",
    "seat_observation_manager",
)


def _real_config() -> dict:
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def started_controller():
    controller = AppContainer(_real_config())
    controller.driver = MagicMock()
    controller.wire_services()
    controller.runtime_loop.init_runtime_queue()
    yield controller


def test_composition_root_initializes_seat_use_cases_and_retires_old_package(started_controller):
    for module_name in RETIRED_SEAT_MODULES:
        assert not (
            Path(__file__).resolve().parents[1]
            / "src/ushareiplay/managers/seat_manager"
            / f"{module_name}.py"
        ).exists()
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"ushareiplay.managers.seat_manager.{module_name}")

    assert isinstance(started_controller.seat_service, SeatService)
    assert isinstance(started_controller.seat_observation, SeatObservationService)


def test_retired_seat_attributes_are_gone_from_the_controller(started_controller):
    for attr in RETIRED_CONTROLLER_ATTRS:
        assert not hasattr(started_controller, attr), (
            f"AppController 仍暴露 {attr}，接线层已不再构造它"
        )


def test_observation_and_seat_service_share_panel_driver(started_controller):
    assert isinstance(started_controller.seat_panel_driver, SeatPanelDriver)
    assert started_controller.seat_observation._panel is started_controller.seat_panel_driver
    assert started_controller.seat_service._panel is started_controller.seat_panel_driver
    assert started_controller.seat_panel_driver.panel_reader is started_controller.seat_panel_reader


def test_real_startup_path_completes_without_missing_singletons(started_controller):
    for attr in (
        "soul_handler",
        "music_handler",
        "seat_service",
        "seat_observation",
        "command_manager",
        "event_manager",
        "timer_manager",
    ):
        assert getattr(started_controller, attr, None) is not None, (
            f"启动路径没有装配 {attr}"
        )
    assert started_controller._runtime_queue_drainer is not None


async def test_runtime_queue_drains_through_the_real_startup_wiring(started_controller):
    await started_controller.message_queue.put_message(
        MessageInfo(content="在吗", nickname="路人", source="chat_scan")
    )

    drained, commands = await started_controller._runtime_queue_drainer.drain()

    assert (drained, commands) == (1, 0)
    assert await started_controller.message_queue.get_all_messages() == {}


async def test_seat_service_from_the_startup_path_actually_executes(started_controller):
    assert started_controller.seat_service.check_seats_state() is False
    assert await started_controller.seat_service.prepare_for_chat_scan() is True
    assert started_controller.seat_panel_driver.expanded is False


@pytest.fixture(autouse=True)
def _silence_startup_logging():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
