"""接线层收口（票 #401）：组合根只构造一个座位子系统。

合并前 `AppController._init_handlers` 逐个 initialize 四个座位旧单例，再交给
`SeatManager` 接线，观测器则挂在独立的 `SeatUIManager` 上。本文件钉住三件事：

1. **接线层只构造一个座位对象** —— 真实实现只有 `SeatSubsystem` 一处（票 #400）；
2. **观测器的面板委派来自子系统** —— 不再依赖独立 `SeatUIManager`，且
   `bind_handler` 仍然换得到驱动（ADR-0009 第 5 条要求的「同步更新观测器及其
   UI 委派」）；
3. **真实启动路径跑得通** —— 真的跑一遍 `AppController._init_handlers()` 再真的
   排空一轮运行时队列。缺单例依赖必须当场炸出来，手搭替身盖不住这条路径。

本文件不去改共用的 tests/seat_fixtures.py（别的票也在改它）：它要的是能钉住面板
动作时序的细粒度替身，而这里要的是**接线层本身真的跑一遍**，两者没法共用一套台子。
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from ushareiplay.core.app_controller import AppController
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager import SeatManager
from ushareiplay.managers.seat_manager.reservation import ReservationManager
from ushareiplay.managers.seat_manager.seat_check import SeatCheckManager
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
from ushareiplay.managers.seat_manager.seating import SeatingManager
from ushareiplay.models.message_info import MessageInfo

# 合并前由接线层逐个 initialize 的四个旧单例（票 #402 连同它们一起退役）。
LEGACY_SEAT_SINGLETONS = (
    SeatUIManager,
    SeatCheckManager,
    ReservationManager,
    SeatingManager,
)

# 接线层上挂过、现在必须消失的四个属性。
RETIRED_CONTROLLER_ATTRS = (
    "seat_ui_manager",
    "seat_check_manager",
    "reservation_manager",
    "seating_manager",
)


def _real_config() -> dict:
    """真实 config.yaml：启动路径要的就是这份 selector 与命令表。"""
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def started_controller(initialized_test_singletons):
    """真跑一遍组合根启动路径的 AppController。

    conftest 的 autouse fixture 会先初始化一批无参单例，这里先全部清干净，
    免得 `_init_handlers` 撞上「already initialized」。driver 是 MagicMock：
    构造函数只碰 driver 表面属性，不做设备 I/O（见 app_controller.start_up 的注释）。
    """
    Singleton.reset_all_instances()
    # 类属性兜底的 ui_lock 深度是跨实例的，上一个测试漏下值就会自锁死。
    AppController._ui_lock_owner = None
    AppController._ui_lock_depth = 0

    controller = AppController.__new__(AppController)
    controller.__init__(_real_config())
    controller.driver = MagicMock()
    controller._init_handlers()
    yield controller
    Singleton.reset_all_instances()


# ---------------------------------------------------------------------------
# 1. 接线层只构造一个座位对象
# ---------------------------------------------------------------------------
def test_composition_root_initializes_only_the_seat_subsystem(started_controller):
    """四个旧单例不再由组合根构造（票 #401 的收口点）。"""
    for legacy in LEGACY_SEAT_SINGLETONS:
        assert not legacy.is_initialized(), (
            f"{legacy.__name__} 仍被接线层 initialize，真实实现应只有 SeatSubsystem 一处"
        )

    assert started_controller.seat_manager is SeatManager.instance()
    assert started_controller.seat_manager.subsystem is not None


def test_retired_seat_attributes_are_gone_from_the_controller(started_controller):
    """删掉的属性不能留成 None 占位：读者会被无声地引到空对象上。"""
    for attr in RETIRED_CONTROLLER_ATTRS:
        assert not hasattr(started_controller, attr), (
            f"AppController 仍暴露 {attr}，接线层已不再构造它"
        )


# ---------------------------------------------------------------------------
# 2. 观测器的面板委派来自子系统
# ---------------------------------------------------------------------------
def test_observation_manager_receives_the_subsystem_panel(started_controller):
    """观测器的面板委派就是子系统自己的面板入口，不是独立 SeatUIManager。"""
    subsystem = started_controller.seat_manager.subsystem
    panel_delegate = started_controller.seat_observation_manager.seat_ui

    assert panel_delegate is not None, "面板委派解析不到，重扫会 AttributeError"
    assert panel_delegate is subsystem.panel
    assert not isinstance(panel_delegate, SeatUIManager)

    # 面板动作最终落在唯一那份 SeatPanelDriver 上（#395 的唯一实现）。
    assert isinstance(subsystem.panel_driver, SeatPanelDriver)
    assert panel_delegate.driver is subsystem.panel_driver


def test_panel_delegate_keeps_the_legacy_seat_ui_contract(started_controller):
    """观测器用到的三个面板动作必须在委派上存在（否则重扫当场 AttributeError）。"""
    panel_delegate = started_controller.seat_observation_manager.seat_ui

    assert callable(panel_delegate.expand_and_find_desks)
    assert callable(panel_delegate.collapse_seats)
    assert callable(panel_delegate.scroll_to_row)


def test_bind_handler_still_syncs_the_observation_panel_delegate(started_controller):
    """ADR-0009 第 5 条：bind_handler 仍要同步观测器**及其 UI 委派**。

    委派从旧句柄换成子系统的面板适配层之后，换手必须还能走到驱动 ——
    驱动的 logger 是构造期快照的（见 seat_panel_driver.handler setter），
    换不到就等于让它一直往旧 handler 的 logger 上写。
    """
    observation = started_controller.seat_observation_manager
    driver = started_controller.seat_manager.subsystem.panel_driver
    replacement = SimpleNamespace(logger=MagicMock(), controller=None)

    observation.bind_handler(replacement)

    assert observation.handler is replacement
    assert observation.seat_ui.handler is replacement
    assert driver.handler is replacement
    assert driver.logger is replacement.logger


# ---------------------------------------------------------------------------
# 3. 真实启动路径 + 运行时队列集成
# ---------------------------------------------------------------------------
def test_real_startup_path_completes_without_missing_singletons(started_controller):
    """_init_handlers 真跑一遍：少一个单例依赖就必须在这里炸出来。"""
    for attr in (
        "soul_handler",
        "music_handler",
        "seat_manager",
        "seat_observation_manager",
        "command_manager",
        "event_manager",
        "timer_manager",
    ):
        assert getattr(started_controller, attr, None) is not None, (
            f"启动路径没有装配 {attr}"
        )
    # 运行时队列 drainer 由同一次启动构造，接缝不能只在单测替身里成立。
    assert started_controller._runtime_queue_drainer is not None


async def test_runtime_queue_drains_through_the_real_startup_wiring(started_controller):
    """真的排空一轮运行时队列：MessageQueue -> drainer -> CommandManager -> 公屏。"""
    await MessageQueue.instance().put_message(
        MessageInfo(content="在吗", nickname="路人", source="chat_scan")
    )

    drained, commands = await started_controller._runtime_queue_drainer.drain()

    assert (drained, commands) == (1, 0)
    # 队列被排空，没有残留条目在下一圈再走一遍。
    assert await MessageQueue.instance().get_all_messages() == {}


async def test_seat_subsystem_from_the_startup_path_actually_executes(started_controller):
    """接线层造出来的子系统要能真跑一个公开接口，不只是对象存在。

    走的是 `prepare_for_chat_scan`：客房守卫 -> 子系统 -> 面板入口 -> 面板驱动，
    一整条都是接线层刚构造出来的那份实现。缺任何一环都会在这里炸。
    """
    subsystem = started_controller.seat_manager.subsystem

    # MagicMock driver 读不到展开按钮，判据就是「面板没展开」，因此走收起分支。
    assert subsystem.check_seats_state() is False
    assert await started_controller.seat_manager.prepare_for_chat_scan() is True
    assert subsystem.panel_driver.expanded is False


def test_observation_manager_resolves_its_panel_after_a_driver_restart(started_controller):
    """驱动崩溃重启会换 handler：观测器换手后面板委派仍指向同一份驱动。"""
    observation = started_controller.seat_observation_manager
    subsystem = started_controller.seat_manager.subsystem
    replacement = SimpleNamespace(logger=MagicMock(), controller=None)

    observation.bind_handler(replacement)

    assert observation.seat_ui is subsystem.panel
    assert subsystem.panel.driver is subsystem.panel_driver
    # 换手不许把面板委派换成另一个对象，否则驱动上缓存的展开状态会分叉。
    assert subsystem.panel.driver.handler is replacement


@pytest.fixture(autouse=True)
def _silence_startup_logging():
    """启动路径按铁律只在有行为时打 INFO；这里只关心接线，不关心控制台。"""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


