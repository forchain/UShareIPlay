"""组合根（Composition Root）：全系统唯一导入具体出站适配器并完成装配的模块。

构造不做任何设备 I/O；`start_up()` 是唯一一处设备与驱动启动入口。
"""

from __future__ import annotations

import asyncio
import os
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import StaleElementReferenceException, WebDriverException

from ushareiplay.adapters.inbound.runtime.command_manager import CommandManager
from ushareiplay.adapters.inbound.runtime.config_reload_manager import ConfigReloadManager
from ushareiplay.adapters.inbound.runtime.hook_command_sink import QueueHookCommandSink
from ushareiplay.adapters.inbound.runtime.keyword_command_sink import QueueKeywordCommandSink
from ushareiplay.adapters.inbound.runtime.keyword_nl_fallback import (
    NaturalLanguageFallbackAdapter,
    PlaybackInfoProvider,
    RoomInfoProvider,
)
from ushareiplay.adapters.inbound.runtime.keyword_presence import InfoManagerPresence
from ushareiplay.adapters.inbound.runtime.message_manager import MessageManager
from ushareiplay.adapters.inbound.runtime.message_queue import MessageQueue
from ushareiplay.adapters.inbound.runtime.post_party_create_automation import (
    PostPartyCreateAutomation,
)
from ushareiplay.adapters.inbound.runtime.timer_message_sink import QueueTimerMessageSink
from ushareiplay.adapters.inbound.runtime.user_memory_chat_log import (
    UserMemoryChatLogRecorder,
)
from ushareiplay.adapters.inbound.ui_events.event_manager import EventManager
from ushareiplay.adapters.outbound.appium.driver_lifecycle import DriverLifecycle
from ushareiplay.adapters.outbound.appium.qq_music import (
    QQMusicHandler,
    QQMusicMediaSession,
    QQMusicUIDriver,
)
from ushareiplay.adapters.outbound.appium.qq_music.music_manager import MusicManager
from ushareiplay.adapters.outbound.appium.soul.luck_pack_driver import SoulLuckPackDriver
from ushareiplay.adapters.outbound.appium.soul.message_dispatch import MessageDispatch
from ushareiplay.adapters.outbound.appium.soul.mic_control import SoulMicControl
from ushareiplay.adapters.outbound.appium.soul.online_drawer_driver import (
    SoulOnlineDrawerDriver,
)
from ushareiplay.adapters.outbound.appium.soul.online_list_source import SoulOnlineListSource
from ushareiplay.adapters.outbound.appium.soul.party_driver import SoulPartyDriver
from ushareiplay.adapters.outbound.appium.soul.recovery_manager import RecoveryManager
from ushareiplay.adapters.outbound.appium.soul.room_profile import (
    SoulDrawerDriver,
    SoulPartySettingsDriver,
    SoulRoomProfileSurface,
)
from ushareiplay.adapters.outbound.appium.soul.seat_invite_driver import SeatInviteDriver
from ushareiplay.adapters.outbound.appium.soul.seat_panel_driver import SeatPanelDriver
from ushareiplay.adapters.outbound.appium.soul.seat_panel_reader import SeatPanelReader
from ushareiplay.adapters.outbound.appium.soul.soul_handler import SoulHandler
from ushareiplay.adapters.outbound.llm.memory_distiller import LLMMemoryDistiller
from ushareiplay.adapters.outbound.llm.natural_language_resolver import (
    OpenAICompatibleNaturalLanguageResolver,
)
from ushareiplay.adapters.outbound.persistence.chat_log_repository import (
    TortoiseChatLogRepository,
)
from ushareiplay.adapters.outbound.persistence.keyword_repository import (
    TortoiseKeywordRepository,
)
from ushareiplay.adapters.outbound.persistence.room_state_store import JsonRoomStateStore
from ushareiplay.adapters.outbound.persistence.seat_reservation_repository import (
    TortoiseSeatReservationRepository,
)
from ushareiplay.adapters.outbound.persistence.timer_repository import (
    TortoiseTimerRepository,
)
from ushareiplay.adapters.outbound.persistence.user_event_hook_repository import (
    TortoiseUserEventHookRepository,
)
from ushareiplay.adapters.outbound.persistence.user_memory_repository import (
    TortoiseUserMemoryRepository,
)
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository
from ushareiplay.adapters.outbound.system.clock import SystemClock
from ushareiplay.adapters.outbound.system.config_loader import ConfigLoader
from ushareiplay.adapters.outbound.system.keyword_config import YamlKeywordConfigSource
from ushareiplay.adapters.outbound.system.network_bridge import (
    diagnose_connection_error,
    ensure_appium_endpoint,
)
from ushareiplay.adapters.outbound.system.runtime_logging import get_runtime_logging
from ushareiplay.bootstrap.runtime_loop import RuntimeLoop
from ushareiplay.core.observability import Observability, new_run_id
from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)
from ushareiplay.core.ui_session_lease import UISessionLease
from ushareiplay.modules.command.domain import CommandCatalogue
from ushareiplay.modules.command.use_cases import (
    KeywordUseCases,
    ResolveNaturalLanguage,
    SleepManager,
)
from ushareiplay.modules.mic.use_cases import ToggleMic
from ushareiplay.modules.playback import (
    AdjustVolume,
    PauseResume,
    PlayNext,
    PlaySong,
    PlaybackBroadcaster,
    PlaybackMuting,
    PlaylistSession,
    QueryLyrics,
    SetAccompaniment,
    SetPlayMode,
    SkipSong,
)
from ushareiplay.modules.room import (
    InfoManager,
    LuckPackService,
    ManageAdmin,
    OnlineDrawer,
    PartyLifecycleState,
    PartyService,
    PresenceTracker,
    RoomAdmins,
    RoomProfileManager,
    RoomStateService,
    UserEventHooks,
    UserProfileActions,
)
from ushareiplay.modules.seat.use_cases import SeatObservationService, SeatService
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.timer.use_cases import TimerUseCases
from ushareiplay.modules.user.domain import MemorySettings
from ushareiplay.modules.user.use_cases import UserMemoryService


class AppContainer:
    """组合根：装配领域用例与适配器，并管理驱动与运行时循环生命周期。"""

    _ui_session_lease: Optional[UISessionLease] = None
    runtime_loop: Optional[RuntimeLoop] = None

    def __init__(self, config):
        # 组合根是配置视图的唯一所有者：根配置与各应用段的读取都从这里
        # 出去，下游拿到的是类型化视图而不是裸 dict（ADR-0012）。
        self.config = config if isinstance(config, ConfigView) else ConfigView(config)
        # 启动即校验：必需的元素选择器缺任何一项都当场失败。
        self.config.validate_required_elements()

        self.run_id = new_run_id()
        self.obs = Observability(run_id=self.run_id)
        self.obs.emit("app.start", ctx={"component": "AppContainer"})
        self.runtime_logging = get_runtime_logging()

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
        # 构造不做设备 I/O：驱动与应用启动在 start_up() 里显式调用。
        self._driver_started = False
        self._services_wired = False

        self.soul_handler = None
        self.music_handler = None
        self.logger = None

        self.command_catalogue = None
        self.room_state = None
        self.room_admins = None
        self.presence = None
        self.sleep_manager = None
        self.message_queue = None
        self.recovery_manager = None
        self.message_manager = None
        self.message_dispatch = None
        self.mic_control = None
        self.toggle_mic = None
        self.music_manager = None
        self.music_media_session = None
        self.ui_driver = None
        self.playback_muting = None
        self.timer_manager = None
        self.command_manager = None
        self.playback_broadcaster = None
        self.party_lifecycle = None
        self.room_profile_manager = None
        self.playlist_session = None
        self.play_song = None
        self.skip_song = None
        self.play_next = None
        self.set_play_mode = None
        self.set_accompaniment = None
        self.query_lyrics = None
        self.pause_resume = None
        self.adjust_volume = None
        self.info_manager = None
        self.online_drawer = None
        self.manage_admin = None
        self.user_profile_actions = None
        self.party_service = None
        self.luck_pack = None
        self.online_list_source = None
        self.user_memory = None
        self.keyword_use_cases = None
        self.user_event_hooks = None
        self.seat_panel_reader = None
        self.seat_panel_driver = None
        self.seat_invite_driver = None
        self.seat_observation = None
        self.seat_service = None
        self.post_party_create_automation = None
        self.event_manager = None
        self.config_reload_manager = None
        self.user_repository = None
        self.clock = None

        self._ui_session_lease: Optional[UISessionLease] = None
        self.runtime_loop = RuntimeLoop(
            config=self.config,
            obs=self.obs,
            lease=self.ui_session_lease,
            room_owner_provider=lambda: self.room_owner,
            agent_command_dir=Path(".agent") / "commands",
            driver_provider=lambda: self.driver,
            stale_element_exceptions=(StaleElementReferenceException,),
            driver_exceptions=(WebDriverException,),
        )

        self.driver_recovery_context = DriverRecoveryContext(
            reinitialize_driver=self.reinitialize_driver,
            obs=self.obs,
        )
        self.command_runtime_context = CommandRuntimeContext(
            lease=self.ui_session_lease,
            controller=self,
        )
        self.event_runtime_context = EventRuntimeContext(
            lease=self.ui_session_lease,
            paused=lambda: bool(
                self.runtime_loop.runtime_input
                and self.runtime_loop.runtime_input.paused
            ),
        )

    def start_up(self) -> None:
        """建立 Appium 驱动并拉起目标应用（唯一一处设备 I/O）。"""
        if self._driver_started:
            return
        try:
            self.driver_lifecycle.initialize()
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
        return RolePolicy(self.config).room_owner

    @property
    def ui_session_lease(self) -> UISessionLease:
        if self._ui_session_lease is None:
            self._ui_session_lease = UISessionLease(
                is_paused=lambda: bool(
                    self.runtime_loop
                    and self.runtime_loop.runtime_input
                    and self.runtime_loop.runtime_input.paused
                ),
                logger=lambda: getattr(self, "logger", None),
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
        async with self.ui_session_lease.acquire(reason):
            yield

    @property
    def input_queue(self):
        return self.runtime_loop.input_queue

    @property
    def is_running(self) -> bool:
        return self.runtime_loop.is_running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        self.runtime_loop.is_running = value

    @property
    def runtime_input(self):
        return self.runtime_loop.runtime_input

    @property
    def _runtime_queue_drainer(self):
        return self.runtime_loop.runtime_queue_drainer

    @property
    def _agent_command_spool(self):
        return self.runtime_loop.agent_command_spool

    @property
    def _status_reporter(self):
        return self.runtime_loop.status_reporter

    def _start_apps(self):
        """通过Appium server启动QQ Music（Soul app已在创建driver时自动启动）"""
        try:
            print("正在通过Appium server启动QQ Music...")

            qq_music_package = self.config.music.require("package_name")
            qq_music_activity = self.config.music.require("search_activity")
            print(f"正在启动QQ Music: {qq_music_package}/{qq_music_activity}")

            self.driver.execute_script(
                "mobile: shell",
                {"command": f"am start -n {qq_music_package}/{qq_music_activity}"},
            )
            print("QQ Music启动成功")
            time.sleep(1)

            soul_package = self.config.soul.require("package_name")
            soul_activity = self.config.soul.require("chat_activity")
            print(f"切换回Soul app: {soul_package}/{soul_activity}")

            self.driver.execute_script(
                "mobile: shell",
                {"command": f"am start -n {soul_package}/{soul_activity}"},
            )
            print("Soul app已激活")
            time.sleep(1)

            print("应用启动完成")

        except Exception as e:
            self.obs.emit("app.error", level="ERROR", ctx={"where": "_start_apps", "error": str(e)})
            print(f"通过Appium启动应用时发生错误: {str(e)}")
            raise

    def _init_driver(self):
        options = AppiumOptions()
        device = self.config.section("device")

        options.set_capability("platformName", device.require("platform_name"))
        options.set_capability("platformVersion", device.require("platform_version"))
        options.set_capability("deviceName", device.require("name"))
        options.set_capability("automationName", device.require("automation_name"))
        options.set_capability("noReset", device.require("no_reset"))

        options.set_capability("appPackage", self.config.soul.require("package_name"))
        options.set_capability("appActivity", self.config.soul.require("chat_activity"))

        appium = self.config.section("appium")
        appium_host = os.getenv("APPIUM_HOST") or appium.require("host")
        appium_port = os.getenv("APPIUM_PORT") or str(appium.require("port"))

        try:
            target_port = int(appium_port)
            bridge = self._network_bridge
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
                    bridge.stop()
                    self._network_bridge = None
                final_host, final_port, new_bridge = ensure_appium_endpoint(
                    appium_host, target_port
                )
                if new_bridge:
                    self._network_bridge = new_bridge
        except Exception as e:
            if self.logger:
                self.logger.error("Appium 连接检测失败:\n%s", str(e))
            else:
                print(f"Appium 连接检测失败:\n{str(e)}")
            raise

        server_url = f"http://{final_host}:{final_port}"
        try:
            driver = webdriver.Remote(command_executor=server_url, options=options)
        except Exception as e:
            diag = diagnose_connection_error(final_host, final_port, e)
            if self.logger:
                self.logger.error("初始化 Appium Remote Driver 失败:\n%s", diag)
            else:
                print(f"初始化 Appium Remote Driver 失败:\n{diag}")
            raise
        driver.update_settings({
            "waitForIdleTimeout": 0,
            "waitForSelectorTimeout": 2000,
            "waitForPageLoad": 2000,
        })
        return driver

    def register_driver_subscriber(self, component) -> None:
        self.driver_lifecycle.attach(component)

    def reinitialize_driver(self) -> bool:
        return self.driver_lifecycle.reinitialize()

    @property
    def driver(self):
        return self.driver_lifecycle.driver

    @driver.setter
    def driver(self, value):
        self.driver_lifecycle._driver = value

    @property
    def _driver_subscribers(self):
        return self.driver_lifecycle.subscribers

    def _on_driver_reinit(self, _driver) -> None:
        if self.soul_handler and hasattr(self.soul_handler, "key_actions"):
            self.soul_handler.key_actions.switch_to_app()
        if self.logger:
            self.logger.info("Driver reinitialized and propagated to subscribers")

    def wire_services(self) -> None:
        """按既定启动依赖顺序构造并注入全部处理器、适配器与领域用例。"""
        if self._services_wired:
            return
        try:
            self.soul_handler = SoulHandler(self.driver, self.config.soul, self)
            self.register_driver_subscriber(self.soul_handler)
            self.music_handler = QQMusicHandler(self.driver, self.config.music, self)
            self.register_driver_subscriber(self.music_handler)
            self.logger = self.soul_handler.logger

            self.logger.info("创建 manager 实例...")

            self.user_repository = TortoiseUserRepository()
            self.clock = SystemClock()
            self.command_catalogue = CommandCatalogue.from_config(self.config)
            self.command_catalogue.validate()

            self.room_state = RoomStateService(
                default_party_id=self.config.soul.value("default_party_id"),
                current_party_id=lambda: self.soul_handler.party_id,
                catalogue=self.command_catalogue,
                store=JsonRoomStateStore(),
                logger=self.logger,
            )
            self.room_admins = RoomAdmins()
            self.presence = PresenceTracker(
                logger=self.logger,
                on_user_enter=lambda name: self.command_manager.notify_user_enter(name),
                on_user_leave=lambda name: self.command_manager.notify_user_leave(name),
            )

            self.sleep_manager = SleepManager(
                self.config, catalogue=self.command_catalogue
            )
            self.message_queue = MessageQueue()
            self.recovery_manager = RecoveryManager(
                self.soul_handler, room_state=self.room_state
            )
            self.message_manager = MessageManager(
                self.soul_handler,
                presence=self.presence,
                message_queue=self.message_queue,
                users=self.user_repository,
                chat_logger_factory=self.runtime_logging.attach_chat_logger,
            )
            self.message_dispatch = MessageDispatch(self.soul_handler)
            self.mic_control = SoulMicControl(self.soul_handler)
            self.toggle_mic = ToggleMic(self.mic_control)
            self.music_manager = MusicManager(
                music_handler=self.music_handler,
                config=self.config,
            )
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
            self.message_manager.configure_playback_muting(self.playback_muting)
            self.timer_manager = TimerUseCases(
                repository=TortoiseTimerRepository(),
                clock=self.clock,
                sink=QueueTimerMessageSink(self.message_queue),
                logger=self.logger,
            )
            self.command_manager = CommandManager(
                self.soul_handler,
                self.sleep_manager,
                room_state=self.room_state,
                users=self.user_repository,
                clock=self.clock,
                message_dispatch=self.message_dispatch,
            )
            self.command_manager.controller = self
            self.command_manager.configure_runtime(self.command_runtime_context)
            self.message_manager.configure_command_manager(self.command_manager)

            self.playback_broadcaster = PlaybackBroadcaster(
                self.soul_handler,
                music_manager=self.music_manager,
                messenger=self.message_dispatch.bind_handler(self.soul_handler),
                config=self.config.soul,
                logger=self.logger,
            )
            self.party_lifecycle = PartyLifecycleState()
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
                avatar_usernames=self.user_repository.get_all_avatar_usernames,
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
                users=self.user_repository,
                logger=self.logger,
            )
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
            self.online_list_source = SoulOnlineListSource(
                drawer=self.online_drawer,
                users=self.user_repository,
                presence=self.presence,
                room_state=self.room_state,
                ui_session=self.ui_session,
                logger=self.logger,
            )

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
                users=self.user_repository,
                memories=TortoiseUserMemoryRepository(),
                chat_logs=TortoiseChatLogRepository(),
                distiller=LLMMemoryDistiller(
                    llm_client,
                    timeout=memory_settings.timeout,
                ),
                settings=memory_settings,
            )
            self.command_manager.user_memory = self.user_memory

            self.keyword_use_cases = KeywordUseCases(
                repository=TortoiseKeywordRepository(),
                users=self.user_repository,
                presence=InfoManagerPresence(self.info_manager),
                queue=QueueKeywordCommandSink(self.message_queue),
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
            self.message_manager.configure_keywords(self.keyword_use_cases)
            self.user_event_hooks = UserEventHooks(
                repository=TortoiseUserEventHookRepository(),
                users=self.user_repository,
                sink=QueueHookCommandSink(self.message_queue),
                presence=self.presence,
                memory=self.user_memory,
                logger=self.logger,
            )
            self.command_manager.user_event_hooks = self.user_event_hooks

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
                users=self.user_repository,
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
            self.room_state.add_room_change_listener(
                self.room_profile_manager.invalidate_ui_state
            )
            self.post_party_create_automation = PostPartyCreateAutomation(
                self, message_queue=self.message_queue
            )

            self.logger.info("初始化命令解析器...")
            self.command_manager.initialize_parser(self.command_catalogue)

            self.logger.info("初始化事件管理器...")
            self.event_manager = EventManager(self.soul_handler)
            self.event_manager.configure_runtime(self.event_runtime_context)
            self.event_manager.initialize_events()
            self.logger.info("事件管理器初始化完成")

            self.config_reload_manager = self._build_config_reload_manager()

            self.runtime_loop.bind_services(
                logger=self.logger,
                soul_handler=self.soul_handler,
                command_manager=self.command_manager,
                event_manager=self.event_manager,
                timer_manager=self.timer_manager,
                user_memory=self.user_memory,
                keyword_use_cases=self.keyword_use_cases,
                party_service=self.party_service,
                message_dispatch=self.message_dispatch,
                message_queue=self.message_queue,
                config_reload_manager=self.config_reload_manager,
                post_party_create_automation=self.post_party_create_automation,
            )

            self._services_wired = True
            self.logger.info("Handlers and managers initialized successfully")
            self.logger.info("所有 handlers 和 managers 初始化完成")
        except Exception:
            if self.logger:
                self.logger.error(f"Error initializing handlers: {traceback.format_exc()}")
            raise

    def _build_config_reload_manager(self) -> ConfigReloadManager:
        if self.soul_handler.config is not self.config.soul:
            raise AssertionError(
                "soul_handler.config 必须是 container.config.soul 同一个视图，"
                "否则热重载写不进机器人真正在用的配置"
            )
        if self.music_handler.config is not self.config.music:
            raise AssertionError(
                "music_handler.config 必须是 container.config.music 同一个视图，"
                "否则热重载写不进机器人真正在用的配置"
            )
        return ConfigReloadManager(
            config=self.config,
            event_manager=self.event_manager,
            command_manager=self.command_manager,
            sleep_manager=self.sleep_manager,
            room_state=self.room_state,
            load_config=ConfigLoader.load_config,
        )

    async def start_monitoring(self):
        if self.logger:
            self.logger.info("开始启动监控...")
        self.wire_services()
        return await self.runtime_loop.start_monitoring()

    async def stop(self):
        await self.runtime_loop.stop()

    async def shutdown(self):
        await self.runtime_loop.stop()
        self.driver_lifecycle.shutdown()

        if self._network_bridge:
            try:
                self._network_bridge.stop()
            except Exception:
                pass
            self._network_bridge = None
