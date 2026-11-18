import asyncio
import os
import queue
import sys
import threading
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import WebDriverException, StaleElementReferenceException

from ushareiplay.adapters.inbound.runtime.keyword_command_sink import QueueKeywordCommandSink
from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
    NaturalLanguageFallbackAdapter,
    PlaybackInfoProvider,
    RoomInfoProvider,
)
from ushareiplay.adapters.inbound.runtime.keyword_presence import InfoManagerPresence
from ushareiplay.adapters.inbound.runtime.user_memory_chat_log import (
    UserMemoryChatLogRecorder,
)
from ushareiplay.adapters.inbound.runtime.timer_message_sink import QueueTimerMessageSink
from ushareiplay.adapters.outbound.persistence.keyword_repository import (
    TortoiseKeywordRepository,
)
from ushareiplay.adapters.outbound.persistence.timer_repository import TortoiseTimerRepository
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.adapters.outbound.system.keyword_config import YamlKeywordConfigSource
from ushareiplay.modules.command.use_cases import KeywordUseCases
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.timer.use_cases import TimerUseCases
from ushareiplay.core.driver_lifecycle import DriverLifecycle
from ushareiplay.modules.command.domain import CommandCatalogue
from ushareiplay.core.console_log_muter import ConsoleLogMuter
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.post_party_create_automation import PostPartyCreateAutomation
from ushareiplay.adapters.inbound.runtime.runtime_services import (
    RuntimeInputPipeline,
    AgentCommandSpool,
    RuntimeQueueDrainer,
    StatusReporter,
)
from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.ui_session_lease import UISessionLease
from ushareiplay.core.observability import Observability, new_run_id
from ushareiplay.adapters.outbound.appium.qq_music import (
    QQMusicHandler,
    QQMusicMediaSession,
    QQMusicUIDriver,
)
from ushareiplay.handlers.soul_handler import SoulHandler
from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
from ushareiplay.managers.config_reload_manager import ConfigReloadManager
from ushareiplay.modules.playback import (
    AdjustVolume,
    PauseResume,
    PlayNext,
    PlaySong,
    PlaybackMuting,
    PlaylistSession,
    QueryLyrics,
    SetAccompaniment,
    SetPlayMode,
    SkipSong,
)


class AppController(Singleton):
    # UI 独占会话租赁。类属性兜底，让绕过 __init__ 直接构造的测试替身也能安全走
    # ui_session（首次访问时按需创建）。
    _ui_session_lease: Optional[UISessionLease] = None
    # 类属性兜底：绕过 __init__ 的测试替身也能安全读写房间状态与记忆服务。
    room_state = None
    user_memory = None

    def __init__(self, config):
        # 组合根是配置视图的唯一所有者：根配置与各应用段的读取都从这里
        # 出去，下游拿到的是类型化视图而不是裸 dict（ADR-0012）。
        self.config = config if isinstance(config, ConfigView) else ConfigView(config)
        # 启动即校验：必需的元素选择器缺任何一项都当场失败，
        # 而不是等到运行期操作 UI 时才炸。
        self.config.validate_required_elements()

        self.run_id = new_run_id()
        self.obs = Observability(run_id=self.run_id)
        self.obs.emit("app.start", ctx={"component": "AppController"})

        # Appium driver lifecycle is delegated to a dedicated module.
        # AppController only orchestrates startup and subscriber wiring.
        self.driver_lifecycle = DriverLifecycle(
            factory=self._init_driver,
            settings={
                "waitForIdleTimeout": 0,
                "waitForSelectorTimeout": 2000,
                "waitForPageLoad": 2000,
            },
            on_reinit=self._on_driver_reinit,
            obs=self.obs,
        )
        self._network_bridge = None
        # 构造不做设备 I/O：驱动与应用启动在 start_up() 里，由入口在
        # initialize() 之后显式调用。否则任何测试只要构造控制器就会去连设备，
        # 只能靠 `AppController.__new__` 手工拼字段来绕开。
        self._driver_started = False

        self.input_queue = queue.Queue()
        self.agent_command_dir = Path(".agent") / "commands"
        self.is_running = True
        self.in_console_mode = False

        # Initialize handlers using singleton pattern (delayed initialization)
        self.soul_handler = None
        self.music_handler = None
        self.logger = None

        # Command manager will be initialized after handlers are ready
        self.command_manager = None

        # Initialize managers (will be done after handlers are initialized)
        self.seat_service = None
        self.seat_observation = None
        self.recovery_manager = None
        self.music_manager = None
        self.event_manager = None
        self.user_memory = None
        self.post_party_create_automation = None


        # Non-UI operations task
        self._non_ui_task = None

        # 全局 UI 互斥锁：
        # 用于防止后台事件循环（如未知页面自动 back）与命令/UI任务并发操作同一界面。
        # 注意：锁只在 async 逻辑中使用；同步 handler 方法不直接 await。
        self.ui_lock: asyncio.Lock = asyncio.Lock()
        self.driver_recovery_context = DriverRecoveryContext(
            reinitialize_driver=self.reinitialize_driver,
            obs=self.obs,
        )
        self.command_runtime_context = CommandRuntimeContext(
            lease=self.ui_session_lease, controller=self
        )
        self.event_runtime_context = EventRuntimeContext(
            lease=self.ui_session_lease,
            paused=lambda: bool(self.runtime_input and self.runtime_input.paused),
        )

        self._runtime_queue_drainer = None
        self._agent_command_spool = AgentCommandSpool(
            input_queue=self.input_queue,
            command_dir=self.agent_command_dir,
            obs=self.obs,
            config=self.config,
            dispatch_meta=self._dispatch_meta_if_needed,
        )
        self._status_reporter = StatusReporter(
            config=self.config,
            lease=self.ui_session_lease,
            obs=self.obs,
        )
        # 运行时输入管线在 start_monitoring 里构造：它需要 handler 与 timer_manager
        self.runtime_input = None

    def start_up(self) -> None:
        """建立 Appium 驱动并拉起目标应用（唯一一处设备 I/O）。

        与 `DriverLifecycle` 配合：失败时关闭驱动与网络桥，把异常交回入口的
        重试循环，而不是把控制器留在半启动状态。
        """
        if self._driver_started:
            return
        try:
            self.driver_lifecycle.initialize()
            # 使用主driver启动其他应用
            self._start_apps()
        except Exception:
            self.driver_lifecycle.shutdown()
            if self._network_bridge:
                try:
                    self._network_bridge.stop()
                except Exception:
                    pass
            raise
        self._driver_started = True

    @property
    def room_owner(self) -> str:
        from ushareiplay.modules.shared.roles import RolePolicy
        return RolePolicy(self.config).room_owner

    @property
    def ui_session_lease(self) -> UISessionLease:
        """UI 独占会话租赁（按需创建，便于 __new__ 构造的测试替身）。"""
        if self._ui_session_lease is None:
            self._ui_session_lease = UISessionLease(
                is_paused=lambda: bool(
                    getattr(self, "runtime_input", None)
                    and self.runtime_input.paused
                ),
                logger=lambda: self.logger,
            )
        return self._ui_session_lease

    @property
    def ui_lock(self) -> asyncio.Lock:
        return self.ui_session_lease.lock

    @ui_lock.setter
    def ui_lock(self, value: asyncio.Lock):
        self.ui_session_lease.lock = value

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        """
        获取 UI 独占执行权（异步）。
        约定：所有可能改变页面结构/弹窗状态的后台任务（命令、自动处理等）应持有该锁，
        EventManager 的兜底 press_back 也会尊重该锁。

        可重入：同一个 task 嵌套进入时直通。asyncio.Lock 不可重入，而命令派发链
        上的座位流程（reserve_seat -> check_user_specific_seat）本就在锁内，不放行
        会自锁死。外层仍真实持锁，EventRuntimeContext.is_ui_busy() 读的是
        ui_lock.locked()，兜底 back 的抑制语义因此不变。
        """
        async with self.ui_session_lease.acquire(reason):
            yield

    def _start_apps(self):
        """通过Appium server启动QQ Music（Soul app已在创建driver时自动启动）"""
        try:
            print("正在通过Appium server启动QQ Music...")

            # 启动QQ Music
            qq_music_package = self.config.music.require("package_name")
            qq_music_activity = self.config.music.require("search_activity")
            print(f"正在启动QQ Music: {qq_music_package}/{qq_music_activity}")

            # 兼容：某些环境下 driver 可能是 Selenium WebDriver（无 start_activity）。
            # 通过 Appium server 执行 mobile: shell 来启动 Activity（不直连 adb）。
            self.driver.execute_script(
                "mobile: shell",
                {"command": f"am start -n {qq_music_package}/{qq_music_activity}"},
            )
            print("QQ Music启动成功")
            time.sleep(1)  # 等待应用启动

            # 切换回Soul app（主driver默认指向Soul app）
            soul_package = self.config.soul.require("package_name")
            soul_activity = self.config.soul.require("chat_activity")
            print(f"切换回Soul app: {soul_package}/{soul_activity}")

            self.driver.execute_script(
                "mobile: shell",
                {"command": f"am start -n {soul_package}/{soul_activity}"},
            )
            print("Soul app已激活")
            time.sleep(1)  # 等待应用切换

            print("应用启动完成")

        except Exception as e:
            self.obs.emit("app.error", level="ERROR", ctx={"where": "_start_apps", "error": str(e)})
            print(f"通过Appium启动应用时发生错误: {str(e)}")
            raise

    def _init_driver(self):
        options = AppiumOptions()

        device = self.config.section("device")

        # 设置基本能力
        options.set_capability("platformName", device.require("platform_name"))
        options.set_capability(
            "platformVersion", device.require("platform_version")
        )
        options.set_capability("deviceName", device.require("name"))
        options.set_capability(
            "automationName", device.require("automation_name")
        )
        options.set_capability("noReset", device.require("no_reset"))

        # 设置应用信息
        options.set_capability("appPackage", self.config.soul.require("package_name"))
        options.set_capability("appActivity", self.config.soul.require("chat_activity"))

        # 优先从环境变量读取，如果没有再从配置文件读取
        appium = self.config.section("appium")
        appium_host = os.getenv("APPIUM_HOST") or appium.require("host")
        appium_port = os.getenv("APPIUM_PORT") or str(appium.require("port"))

        from ushareiplay.adapters.outbound.system.network_bridge import ensure_appium_endpoint, diagnose_connection_error
        try:
            target_port = int(appium_port)
            bridge = getattr(self, "_network_bridge", None)
            if (
                bridge
                and bridge.is_running
                and bridge.target_host == appium_host
                and bridge.target_port == target_port
            ):
                final_host = bridge.bridge_host
                final_port = bridge.bridge_port
            else:
                if bridge:
                    # A bridge pointed at some other Appium endpoint would send
                    # the driver to the wrong host; drop it instead of reusing it.
                    bridge.stop()
                    self._network_bridge = None
                final_host, final_port, new_bridge = ensure_appium_endpoint(appium_host, target_port)
                if new_bridge:
                    self._network_bridge = new_bridge
        except Exception as e:
            if hasattr(self, "logger") and self.logger:
                self.logger.error("Appium 连接检测失败:\n%s", str(e))
            else:
                print(f"Appium 连接检测失败:\n{str(e)}")
            raise

        server_url = f"http://{final_host}:{final_port}"
        try:
            driver = webdriver.Remote(command_executor=server_url, options=options)
        except Exception as e:
            diag = diagnose_connection_error(final_host, final_port, e)
            if hasattr(self, "logger") and self.logger:
                self.logger.error("初始化 Appium Remote Driver 失败:\n%s", diag)
            else:
                print(f"初始化 Appium Remote Driver 失败:\n{diag}")
            raise
        driver.update_settings({
            "waitForIdleTimeout": 0,  # Don't wait for idle state
            "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
            "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
        })
        return driver

    def register_driver_subscriber(self, component) -> None:
        # Thin shim that delegates to the Driver Lifecycle module so the
        # lifecycle seam owns the subscriber bookkeeping.
        self.driver_lifecycle.attach(component)

    def reinitialize_driver(self) -> bool:
        # 统一的driver重建入口。所有组件检测到driver失效时必须调用此方法。
        # Reentry guard lives in DriverLifecycle so this stays a thin shim.
        return self.driver_lifecycle.reinitialize()

    @property
    def driver(self):
        return self.driver_lifecycle.driver

    @driver.setter
    def driver(self, value):
        # Tests still poke ``controller.driver``; preserve that affordance
        # by routing the assignment through the lifecycle module.
        self.driver_lifecycle._driver = value

    @property
    def _driver_subscribers(self):
        return self.driver_lifecycle.subscribers

    def _on_driver_reinit(self, _driver) -> None:
        # Hook called by DriverLifecycle after a successful reinit.
        if self.soul_handler and hasattr(self.soul_handler, "key_actions"):
            self.soul_handler.key_actions.switch_to_app()
        if self.logger:
            self.logger.info("Driver reinitialized and propagated to subscribers")

    def _toggle_console_mode(self):
        """Toggle console mode on Ctrl+P"""
        if not self.in_console_mode:
            self.logger.info("Entering console mode. Press Ctrl+P again to exit...")
            self.in_console_mode = True
        else:
            self.logger.info("Exiting console mode...")
            self.in_console_mode = False

    def _dispatch_meta_if_needed(self, text: str) -> bool:
        """控制台线程入口：立即切换暂停标志，定时器/中断钩子留给事件循环。

        QQ Music 的 UI 编排是同步 Appium 调用，会把事件循环堵住整段操作时长；
        暂停标志必须在这里同步落下，同步 UI 代码下一次查 `is_interrupted()`
        才能看到。返回 True 表示已消费，不要再投递到输入队列（否则会被再切换
        一次）。
        """
        if not self.runtime_input:
            return False
        loop = getattr(self, "loop", None)
        if not (loop and loop.is_running()):
            return False
        paused = self.runtime_input.toggle_paused(text.strip())
        if paused is None:
            return False
        asyncio.run_coroutine_threadsafe(
            self.runtime_input.apply_pause_side_effects(paused), loop
        )
        return True

    def _console_input(self):
        """Background thread for console input"""
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(errors="replace")
            except Exception:
                pass

        muter = ConsoleLogMuter.get_instance()

        while self.is_running:
            try:
                if self.in_console_mode:
                    user_input = input("Console> ")
                    if user_input.strip():
                        if self.logger:
                            self.logger.critical(f"{user_input}")
                        if not self._dispatch_meta_if_needed(user_input):
                            self.input_queue.put((user_input, "console"))
                else:
                    user_input = input("")
                    if not user_input.strip():
                        # First Enter received: mute console log output and prompt for command
                        muter.mute()
                        try:
                            command = input("Command> ")
                        finally:
                            muter.unmute()
                        if command.strip():
                            if self.logger:
                                self.logger.critical(f"{command}")
                            if not self._dispatch_meta_if_needed(command):
                                self.input_queue.put((command, "console"))
                    else:
                        # User directly entered something without pressing Enter first
                        if self.logger:
                            self.logger.critical(f"{user_input}")
                        if not self._dispatch_meta_if_needed(user_input):
                            self.input_queue.put((user_input, "console"))
            except UnicodeDecodeError as e:
                muter.unmute()
                if self.logger:
                    self.logger.warning(f"Console input decode error: {e}")
                continue
            except EOFError:
                # No interactive stdin (systemd/docker): stop the console thread.
                break
            except KeyboardInterrupt:
                muter.unmute()
                if self.in_console_mode:
                    self.in_console_mode = False
                    if self.logger:
                        self.logger.info("Exiting console mode...")
                else:
                    self.is_running = False
                break
            except Exception as e:
                muter.unmute()
                if self.logger:
                    self.logger.error(f"Console input error: {e}")
                time.sleep(0.5)
                continue

    def _drain_agent_command_spool(self) -> None:
        self._agent_command_spool.drain()

    def _spool_input_loop(self) -> None:
        """Background thread for agent command spool."""
        while self.is_running:
            try:
                self._drain_agent_command_spool()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Spool input error: {e}")
            time.sleep(0.05)

    async def _detect_initial_room_state(self):
        """启动时：找到房间 ID 并交给 PartyManager 核对（与运行期同一判定）。

        这里只做「找到元素并取文本」；主房/客房/群主转让的判定与退房重建都在
        `PartyManager.verify_current_room()`。
        """
        try:
            if not self.soul_handler or not hasattr(self.soul_handler, 'element_finder'):
                return
            room_id_elem = self.soul_handler.element_finder.try_find_element('room_id', log=False)
            if not room_id_elem:
                return
            room_id_text = self.soul_handler.element_finder.get_element_text(room_id_elem)
            if not room_id_text or not isinstance(room_id_text, str):
                return

            await self.party_service.verify_current_room(
                room_id_text.strip(), source="startup"
            )
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Initial room detection skipped: {e}")

    def _init_handlers(self):
        """Initialize handlers after driver is ready"""
        try:
            # Initialize handlers using singleton pattern
            self.soul_handler = SoulHandler.initialize(
                self.driver, self.config.soul, self
            )
            self.register_driver_subscriber(self.soul_handler)
            self.music_handler = QQMusicHandler.initialize(
                self.driver, self.config.music, self
            )
            self.register_driver_subscriber(self.music_handler)
            self.logger = self.soul_handler.logger

            # Initialize managers using singleton pattern (no parameters needed)
            from ushareiplay.adapters.outbound.appium.soul.mic_control import SoulMicControl
            from ushareiplay.modules.mic.use_cases import ToggleMic
            from ushareiplay.managers.music_manager import MusicManager
            from ushareiplay.managers.recovery_manager import RecoveryManager
            from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
            from ushareiplay.adapters.inbound.runtime.message_manager import MessageManager
            from ushareiplay.modules.command.use_cases import SleepManager
            from ushareiplay.modules.room import RoomProfileManager
            from ushareiplay.modules.room import (
                InfoManager,
                LuckPackService,
                PartyLifecycleState,
                PartyService,
                UserProfileActions,
            )
            from ushareiplay.adapters.outbound.appium.soul.luck_pack_driver import (
                SoulLuckPackDriver,
            )
            from ushareiplay.adapters.outbound.appium.soul.party_driver import (
                SoulPartyDriver,
            )
            from ushareiplay.adapters.outbound.appium.soul.room_profile import (
                SoulDrawerDriver,
                SoulPartySettingsDriver,
                SoulRoomProfileSurface,
            )
            from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
            from ushareiplay.adapters.inbound.runtime.hook_command_sink import QueueHookCommandSink
            from ushareiplay.adapters.outbound.appium.soul.online_drawer_driver import (
                SoulOnlineDrawerDriver,
            )
            from ushareiplay.adapters.outbound.appium.soul.online_list_source import SoulOnlineListSource
            from ushareiplay.adapters.outbound.persistence.room_state_store import JsonRoomStateStore
            from ushareiplay.adapters.outbound.persistence.user_event_hook_repository import (
                TortoiseUserEventHookRepository,
            )
            from ushareiplay.adapters.outbound.persistence.user_repository import (
                TortoiseUserRepository,
            )
            from ushareiplay.modules.room.domain import RoomAdmins
            from ushareiplay.modules.room.use_cases import (
                ManageAdmin,
                OnlineDrawer,
                PresenceTracker,
                RoomStateService,
                UserEventHooks,
            )

            # Initialize managers after handlers are ready
            self.logger.info("创建 manager 实例...")
            # Creation is deliberately centralized here. Every other module uses
            # .instance() as a lookup-only API.
            # 命令目录只编译/校验一次：前缀缺模块或前缀重复必须启动即失败，
            # 而不是等用户在公屏敲下命令才暴露。
            self.command_catalogue = CommandCatalogue.from_config(self.config)
            self.command_catalogue.validate()

            # 房间状态与在线集合：组合根各构造一次，注入所有需要它们的组件。
            self.room_state = RoomStateService(
                default_party_id=self.config.soul.value("default_party_id"),
                current_party_id=lambda: self.soul_handler.party_id,
                catalogue=self.command_catalogue,
                store=JsonRoomStateStore(),
                logger=self.logger,
            )
            # 房管名单由房间用例、座位观测与 `:info` 共用同一份事实。
            self.room_admins = RoomAdmins()
            self.presence = PresenceTracker(
                logger=self.logger,
                on_user_enter=lambda name: self.command_manager.notify_user_enter(name),
                on_user_leave=lambda name: self.command_manager.notify_user_leave(name),
            )

            self.sleep_manager = SleepManager(
                self.config, catalogue=self.command_catalogue
            )
            MessageQueue.initialize()
            RecoveryManager.initialize(self.soul_handler, room_state=self.room_state)
            MessageManager.initialize(self.soul_handler, presence=self.presence)
            self.message_dispatch = MessageDispatch.initialize(self.soul_handler)
            self.mic_control = SoulMicControl(self.soul_handler)
            self.toggle_mic = ToggleMic(self.mic_control)
            self.music_manager = MusicManager.initialize()
            self.register_driver_subscriber(self.music_manager)
            self.music_handler._on_demand_marker = self.music_manager.mark_on_demand
            self.music_media_session = QQMusicMediaSession(self.music_handler)
            self.ui_driver = QQMusicUIDriver(
                self.music_handler,
                media_session=self.music_manager,
                quality_checker=self.music_manager,
                config=self.config,
            )
            self.playback_muting = PlaybackMuting(
                mic=self.mic_control,
                media_session=self.music_manager,
                config=self.config.soul,
                is_guest_room=lambda: self.room_state.is_guest_room,
                logger=self.logger,
            )
            MessageManager.instance().configure_playback_muting(self.playback_muting)
            self.recovery_manager = RecoveryManager.instance()
            self.timer_manager = TimerUseCases(
                repository=TortoiseTimerRepository(),
                clock=SystemClock(),
                sink=QueueTimerMessageSink(MessageQueue.instance()),
                logger=self.logger,
            )
            self.command_manager = CommandManager.initialize(
                self.soul_handler, self.sleep_manager, room_state=self.room_state
            )
            self.command_manager.controller = self
            self.command_manager.configure_runtime(self.command_runtime_context)
            self.playback_broadcaster = PlaybackBroadcaster.initialize(self.soul_handler)
            self.party_lifecycle = PartyLifecycleState()
            # 房间档案的唯一所有者：抽屉会话与四类字段（房间标题/话题、派对公告、
            # 派对类型与推荐分发）全在它这里，由组合根构造一次并注入。
            self.room_profile_manager = RoomProfileManager(
                handler=self.soul_handler,
                drawer_driver=SoulDrawerDriver(self.soul_handler),
                settings_driver=SoulPartySettingsDriver(self.soul_handler),
                room_state=self.room_state,
                surface=SoulRoomProfileSurface(self.soul_handler),
                config=self.config.soul,
                messenger=self.message_dispatch.bind_handler(self.soul_handler),
            )
            self.playlist_session = PlaylistSession(
                config=self.config.soul,
                room_profile=self.room_profile_manager,
                online_users=self.presence.get_online_users,
                avatar_usernames=TortoiseUserRepository().get_all_avatar_usernames,
                logger=self.logger,
            )
            self.music_manager._playlist_session = self.playlist_session
            self.music_handler._playlist_session = self.playlist_session
            self.playback_broadcaster._playlist_session = self.playlist_session
            self.play_song = PlaySong(
                ui_driver=self.ui_driver,
                playlist_session=self.playlist_session,
                playback_muting=self.playback_muting,
                logger=self.logger,
            )
            self.skip_song = SkipSong(
                media_session=self.music_manager,
                playlist_session=self.playlist_session,
                playback_muting=self.playback_muting,
            )
            self.play_next = PlayNext(
                next_driver=self.music_handler,
                playlist_session=self.playlist_session,
            )
            self.set_play_mode = SetPlayMode(
                ui_driver=self.ui_driver,
                get_play_mode_key=lambda: self.music_handler.play_mode_key,
                note_play_mode=self.music_handler.note_play_mode,
                logger=self.logger,
            )
            self.set_accompaniment = SetAccompaniment(
                ui_driver=self.ui_driver,
                logger=self.logger,
            )
            self.query_lyrics = QueryLyrics(
                ui_driver=self.ui_driver,
                media_session=self.music_manager,
                logger=self.logger,
            )
            self.pause_resume = PauseResume(
                media_session=self.music_manager,
                playback_control=self.music_media_session,
                playlist_session=self.playlist_session,
                mic=self.mic_control,
                logger=self.logger,
            )
            self.adjust_volume = AdjustVolume(
                playback_control=self.music_media_session,
                logger=self.logger,
            )
            self.info_manager = InfoManager(
                room_state=self.room_state,
                presence=self.presence,
                room_admins=self.room_admins,
                playlist=self.playlist_session,
                playback_cache=self.playback_broadcaster,
                party_lifecycle=self.party_lifecycle,
                users=TortoiseUserRepository(),
                logger=self.logger,
            )
            # 在线用户抽屉的唯一所有者：一次抽屉会话的开、落定、找人、收尾全在它
            # 那里（#428）。端口、命名域解析器与 UI 独占会话都从组合根注入 ——
            # DB 的 canonical 名与 Soul UI 上的可见昵称是两个域，拿 canonical 名去
            # UI 里找人永远不相等（#426 问题陈述 #2）。
            self.online_drawer = OnlineDrawer(
                drawer=SoulOnlineDrawerDriver(self.soul_handler),
                name_resolver=self.info_manager.resolve_visible_username,
                ui_session=self.ui_session,
                logger=self.logger,
            )
            self.manage_admin = ManageAdmin(
                drawer=self.online_drawer,
                admins=self.room_admins,
                logger=self.logger,
            )
            self.user_profile_actions = UserProfileActions(
                drawer=self.online_drawer,
                logger=self.logger,
            )
            self.message_dispatch._user_manager = self.user_profile_actions
            self.party_service = PartyService(
                driver=SoulPartyDriver(self.soul_handler),
                room_state=self.room_state,
                lifecycle=self.party_lifecycle,
                config=self.config.soul,
                messenger=self.message_dispatch.bind_handler(self.soul_handler),
                on_sync_profile=self.room_profile_manager.ensure_synced_on_return,
                on_after_create_notice=self.room_profile_manager.set_default_notice,
                on_after_create_seat=lambda: self.seat_service.find_owner_seat(),
                on_after_create_automation=lambda: self.post_party_create_automation.on_party_created_new(),
                on_memory_consolidate=lambda: self.user_memory.schedule_all(),
                logger=self.logger,
            )
            self.luck_pack = LuckPackService(
                driver=SoulLuckPackDriver(self.soul_handler),
                room_state=self.room_state,
                logger=self.logger,
            )
            # 在线名单抓取：抽屉会话、用户仓储、在线集合与房间人数都由这里注入。
            self.online_list_source = SoulOnlineListSource(
                drawer=self.online_drawer,
                users=TortoiseUserRepository(),
                presence=self.presence,
                room_state=self.room_state,
                ui_session=self.ui_session,
                logger=self.logger,
            )

            # 双层用户记忆：领域用例由组合根装配，LLM 客户端在此注入，
            # 内存/聊天日志仓储背后是 Tortoise 适配器（ADR-0006）。
            from ushareiplay.adapters.outbound.llm.memory_distiller import (
                LLMMemoryDistiller,
            )
            from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
                OpenAICompatibleNaturalLanguageResolver,
            )
            from ushareiplay.adapters.outbound.persistence.chat_log_repository import (
                TortoiseChatLogRepository,
            )
            from ushareiplay.adapters.outbound.persistence.user_memory_repository import (
                TortoiseUserMemoryRepository,
            )
            from ushareiplay.modules.command.use_cases import ResolveNaturalLanguage
            from ushareiplay.modules.user.domain import MemorySettings
            from ushareiplay.modules.user.use_cases import UserMemoryService

            llm_section = self.config.maybe_section("llm")
            llm_cfg = dict(llm_section.data) if llm_section else {}
            if "system_users" not in llm_cfg:
                soul_section = self.config.maybe_section("soul")
                sys_users = (
                    soul_section.value("system_users") if soul_section else None
                ) or self.config.value("system_users")
                if sys_users:
                    llm_cfg["system_users"] = sys_users
            llm_client = OpenAICompatibleNaturalLanguageResolver(llm_cfg)

            memory_settings = MemorySettings.from_config(self.config)
            self.user_memory = UserMemoryService(
                users=TortoiseUserRepository(),
                memories=TortoiseUserMemoryRepository(),
                chat_logs=TortoiseChatLogRepository(),
                distiller=LLMMemoryDistiller(
                    llm_client,
                    timeout=memory_settings.timeout,
                ),
                settings=memory_settings,
            )
            self.command_manager.user_memory = self.user_memory

            # 关键字回复（#547）：仓储、队列出口、在线校验与自然语言兜底都从
            # 组合根注入；自然语言解析走 #548 的 LLM 端口。
            self.keyword_use_cases = KeywordUseCases(
                repository=TortoiseKeywordRepository(),
                users=TortoiseUserRepository(),
                presence=InfoManagerPresence(self.info_manager),
                queue=QueueKeywordCommandSink(MessageQueue.instance()),
                chat_logs=UserMemoryChatLogRecorder(self.user_memory),
                config_source=YamlKeywordConfigSource(),
                fallback=NaturalLanguageFallbackAdapter(
                    commands_config=lambda: self.config.command_entries,
                    catalogue=lambda: self.command_manager.catalogue,
                    room_info=RoomInfoProvider(self.room_state),
                    playback_info=PlaybackInfoProvider(
                        self.playback_broadcaster,
                        self.playlist_session,
                        self.music_handler,
                    ),
                    resolver=ResolveNaturalLanguage(llm_client, llm_cfg),
                    memory=self.user_memory,
                ),
                logger=self.logger,
            )
            MessageManager.instance().configure_keywords(self.keyword_use_cases)
            # 用户事件钩子的唯一所有者：五类事件的命令配置、解析渲染与入队触发都在
            # 这一个模块里，各命令文件只是薄适配器（#422）。
            self.user_event_hooks = UserEventHooks(
                repository=TortoiseUserEventHookRepository(),
                users=TortoiseUserRepository(),
                sink=QueueHookCommandSink(MessageQueue.instance()),
                presence=self.presence,
                memory=self.user_memory,
                logger=self.logger,
            )
            self.command_manager.user_event_hooks = self.user_event_hooks

            from ushareiplay.adapters.outbound.appium.soul.seat_invite_driver import (
                SeatInviteDriver,
            )
            from ushareiplay.adapters.outbound.appium.soul.seat_panel_driver import (
                SeatPanelDriver,
            )
            from ushareiplay.adapters.outbound.appium.soul.seat_panel_reader import (
                SeatPanelReader,
            )
            from ushareiplay.adapters.outbound.persistence.seat_reservation_repository import (
                TortoiseSeatReservationRepository,
            )
            from ushareiplay.modules.seat.use_cases import (
                SeatObservationService,
                SeatService,
            )

            self.seat_panel_reader = SeatPanelReader(
                self.soul_handler, lease=self.ui_session_lease
            )
            self.seat_panel_driver = SeatPanelDriver(
                self.soul_handler,
                panel_reader=self.seat_panel_reader,
                lease=self.ui_session_lease,
            )
            self.seat_invite_driver = SeatInviteDriver(self.soul_handler)
            self.seat_observation = SeatObservationService(
                panel=self.seat_panel_driver,
                room_state=self.room_state,
                room_admins=self.room_admins,
                owner_nickname_provider=lambda: (
                    RolePolicy(self.config).configured_room_owner or None
                ),
                on_focus_change=self.command_manager.notify_focus_count_change,
                logger=self.logger,
            )
            self.seat_service = SeatService(
                panel=self.seat_panel_driver,
                invite_driver=self.seat_invite_driver,
                reservations=TortoiseSeatReservationRepository(),
                users=TortoiseUserRepository(),
                observation=self.seat_observation,
                room_state=self.room_state,
                messenger=self.message_dispatch.bind_handler(self.soul_handler),
                resolve_visible_username=self.info_manager.resolve_visible_username,
                is_user_online=self.info_manager.is_user_online,
                is_user_or_avatar_online=self.info_manager.is_user_or_avatar_online,
                logger=self.logger,
            )
            self.room_state.add_clear_listener(self.seat_observation.clear)
            self.room_state.add_clear_listener(self.playback_muting.reset)
            self.room_state.add_room_change_listener(self.room_profile_manager.invalidate_ui_state)
            self.post_party_create_automation = PostPartyCreateAutomation(self)

            self._status_reporter.soul_handler = self.soul_handler
            self._status_reporter.timer_manager = self.timer_manager

            # Initialize command manager with config
            self.logger.info("初始化命令解析器...")
            self.command_manager.initialize_parser(self.command_catalogue)

            # Initialize event manager
            self.logger.info("初始化事件管理器...")
            self.event_manager = EventManager.initialize(self.soul_handler)
            self.event_manager.configure_runtime(self.event_runtime_context)
            self.event_manager.initialize_events()
            self.logger.info("事件管理器初始化完成")

            # 配置热重载的编排者（#469）：普通对象，组合根构造一次。
            self.config_reload_manager = self._build_config_reload_manager()

            self.logger.info("Handlers and managers initialized successfully")
            self.logger.info("所有 handlers 和 managers 初始化完成")

        except Exception:
            if self.logger:
                self.logger.error(f"Error initializing handlers: {traceback.format_exc()}")
            raise

    def _init_runtime_queue(self) -> None:
        """构造运行时输入管线与队列 drainer。

        drainer 需要管线来观察暂停状态并轮询 !stop，因此先建管线再接线；
        !stop 的中断钩子在组合根显式注册一次。
        """
        self.runtime_input = RuntimeInputPipeline(
            input_queue=self.input_queue,
            room_owner_provider=lambda: self.room_owner,
            logger=self.logger,
            send_screen_message=lambda text: self.message_dispatch.send_screen_message(text),
            timer_manager=self.timer_manager,
            obs=self.obs,
            dump_artifacts=self._dump_readonly_artifacts,
            reload_config=lambda: self.config_reload_manager.reload().render(),
            is_admin=lambda name: RolePolicy(self.config).is_admin(name),
        )
        self._runtime_queue_drainer = RuntimeQueueDrainer(
            handler=self.soul_handler,
            command_manager=self.command_manager,
            send_screen_message=lambda text: self.message_dispatch.send_screen_message(text),
            obs=self.obs,
            logger=self.logger,
            runtime_input=self.runtime_input,
            drain_agent_spool=self._drain_agent_command_spool,
        )
        self.runtime_input.register_interruption_hook(
            self._runtime_queue_drainer.cancel_active_command
        )

    def _build_config_reload_manager(self) -> ConfigReloadManager:
        """构造配置热重载的编排者（#469）。

        依赖在这里显式注入（ADR-0009 §1），注入的必须是各组件手里那个「活的」
        视图：热重载靠原地换内容生效，写进副本的话机器人照旧用旧选择器，
        而控制台还会报「重载成功」—— 所以这里直接把身份不符挡在启动时。
        """
        if self.soul_handler.config is not self.config.soul:
            raise AssertionError(
                "soul_handler.config 必须是 controller.config.soul 同一个视图，"
                "否则热重载写不进机器人真正在用的配置"
            )
        if self.music_handler.config is not self.config.music:
            raise AssertionError(
                "music_handler.config 必须是 controller.config.music 同一个视图，"
                "否则热重载写不进机器人真正在用的配置"
            )
        return ConfigReloadManager(
            config=self.config,
            event_manager=self.event_manager,
            command_manager=self.command_manager,
            sleep_manager=self.sleep_manager,
            room_state=self.room_state,
        )

    async def start_monitoring(self):
        error_count = 0

        # Initialize handlers first
        if self.logger:
            self.logger.info("开始启动监控...")
        self._init_handlers()

        # Load all command modules using CommandManager
        self.logger.info("加载命令模块...")
        self.command_manager.load_all_commands()
        self.logger.info("All command modules loaded")
        self.logger.info("命令模块加载完成")

        # Initialize keyword system and load keywords from config
        self.logger.info("初始化关键字系统...")
        await self.keyword_use_cases.load_keywords_from_config()
        self.logger.info("关键字系统初始化完成")

        # Start async timer manager (loads from DB, migrates from JSON if needed)
        self.logger.info("初始化定时器管理器...")
        await self.timer_manager.start()
        self.logger.info("定时器管理器初始化完成")

        # Start async memory manager worker
        if self.user_memory:
            self.logger.info("初始化记忆管理器...")
            await self.user_memory.start()
            self.logger.info("记忆管理器初始化完成")




        # Start console input thread
        self.logger.info("启动控制台输入线程...")
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()
        spool_thread = threading.Thread(target=self._spool_input_loop)
        spool_thread.daemon = True
        spool_thread.start()
        self.logger.info("控制台输入线程已启动")

        # Detect initial room state on startup
        await self._detect_initial_room_state()

        self._init_runtime_queue()
        self.loop = asyncio.get_running_loop()

        self.logger.info("开始主监控循环...")

        while self.is_running:
            try:
                self._drain_agent_command_spool()
                # Check for console input (高优先级，在事件管理器前处理)
                await self.runtime_input.drain()

                if self.runtime_input.paused:
                    # 暂停期间仍要轮询输入队列，等待 !start 恢复；让出时间片避免空转。
                    await asyncio.sleep(0.5)
                    continue

                if self._runtime_queue_drainer:
                    await self._runtime_queue_drainer.drain()

                outcome = await self.event_manager.process_current_screen()
                if outcome["page_source"]:
                    await self._update_status_from_screen(outcome["screen"])

                # clear error once back to normal
                error_count = 0
                if self.soul_handler.error_count > 9:
                    self.soul_handler.log_error(
                        f"[start_monitoring]too many errors, try to rerun, traceback: {traceback.format_exc()}"
                    )
                    return False

                # 关键：让出事件循环时间片，否则 create_task() 排队的协程无法执行
                await asyncio.sleep(1)
            except KeyboardInterrupt:
                if not self.in_console_mode:
                    self.logger.info("Entering console mode. Press Ctrl+C to exit...")
                    self.in_console_mode = True
                else:
                    self.logger.info("Stopping the monitoring...")
                    self.is_running = False
                    return True
            except StaleElementReferenceException:
                self.soul_handler.log_error(
                    f"[start_monitoring]stale element, traceback: {traceback.format_exc()}"
                )
            except asyncio.CancelledError:
                # ui_session 在 !stop 暂停态下用 CancelledError 硬中断在途 UI 操作。
                # 它是 BaseException，事件链路里的 except Exception 都接不住；必须在
                # 循环边界消费掉，否则会一路逃出 asyncio.run 把进程打死。真正的任务
                # 取消（关停）仍然照常向上传播。
                if asyncio.current_task().cancelling() or not self.runtime_input.paused:
                    raise
                self.logger.info("!stop 中断了本轮处理，运行时进入暂停")
            except WebDriverException:
                self.soul_handler.log_error(
                    f"[start_monitoring]unknown error, traceback: {traceback.format_exc()}"
                )
                error_count += 1
                if error_count > 9:
                    self.is_running = False
                    return False
        return None

    async def _dump_readonly_artifacts(self, reason: str = "") -> None:
        paths = self.obs.paths()
        # page source
        try:
            src = self.driver.page_source
            paths.page_source_xml.write_text(src or "", encoding="utf-8")
            self.obs.emit("artifact.page_source", ctx={"path": str(paths.page_source_xml), "reason": reason})
        except Exception:
            self.obs.emit("artifact.page_source.error", level="ERROR", ctx={"reason": reason, "error": traceback.format_exc()})
        # screenshot
        try:
            ok = self.driver.get_screenshot_as_file(str(paths.screenshot_png))
            self.obs.emit("artifact.screenshot", ctx={"path": str(paths.screenshot_png), "ok": bool(ok), "reason": reason})
        except Exception:
            self.obs.emit("artifact.screenshot.error", level="ERROR", ctx={"reason": reason, "error": traceback.format_exc()})

    async def _update_status_from_screen(self, screen: dict) -> None:
        await self._status_reporter.update(
            screen=screen,
            automation=getattr(self, "post_party_create_automation", None),
        )

    async def stop(self):
        """Stop the application"""
        self.is_running = False

        # Cancel non-UI operations task
        if self._non_ui_task:
            self._non_ui_task.cancel()
            try:
                await self._non_ui_task
            except asyncio.CancelledError:
                pass

        # Stop async timer manager
        await self.timer_manager.stop()
        if self.user_memory:
            await self.user_memory.stop()
        self.logger.info("Application stopped")

    async def shutdown(self):
        """Release per-run resources before the singleton graph is reset."""
        self.is_running = False

        if self._non_ui_task:
            self._non_ui_task.cancel()
            try:
                await self._non_ui_task
            except asyncio.CancelledError:
                pass

        if self.timer_manager and self.timer_manager.is_running():
            await self.timer_manager.stop()

        if self.user_memory:
            await self.user_memory.stop()

        self.driver_lifecycle.shutdown()

        if hasattr(self, "_network_bridge") and self._network_bridge:
            try:
                self._network_bridge.stop()
            except Exception:
                pass
            self._network_bridge = None

        try:
            from ushareiplay.core.singleton import Singleton
            Singleton.reset_all_instances()
        except Exception:
            pass

