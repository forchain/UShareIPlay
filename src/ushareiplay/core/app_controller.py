import asyncio
import os
import queue
import threading
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import WebDriverException, StaleElementReferenceException

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.post_party_create_automation import PostPartyCreateAutomation
from ushareiplay.core.runtime_services import (
    AgentCommandSpool,
    RuntimeQueueDrainer,
    StatusReporter,
)
from ushareiplay.core.runtime_context import (
    CommandRuntimeContext,
    DriverRecoveryContext,
    EventRuntimeContext,
)
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.observability import Observability, new_run_id
from ushareiplay.handlers.qq_music_handler import QQMusicHandler
from ushareiplay.handlers.soul_handler import SoulHandler
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.managers.notice_manager import NoticeManager
from ushareiplay.managers.party_manager import PartyManager


class AppController(Singleton):
    def __init__(self, config):
        self.config = config

        self.run_id = new_run_id()
        self.obs = Observability(run_id=self.run_id)
        self.obs.emit("app.start", ctx={"component": "AppController"})

        # 先创建主driver（会自动启动Soul app）
        self.driver = None
        try:
            self.obs.emit("driver.init.start")
            self.driver = self._init_driver()
            self._driver_subscribers = []
            self.obs.emit("driver.init.ok")

            # 使用主driver启动其他应用
            self._start_apps()
        except Exception:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass
            raise
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
        self.seat_manager = None
        self.recovery_manager = None
        self.music_manager = None
        self.event_manager = None
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
        self.command_runtime_context = CommandRuntimeContext(controller=self)
        self.event_runtime_context = EventRuntimeContext(ui_lock=self.ui_lock)

        # Driver重建防护标志
        self._is_reinitializing = False
        self._runtime_queue_drainer = None
        self._agent_command_spool = AgentCommandSpool(
            input_queue=self.input_queue,
            command_dir=self.agent_command_dir,
            obs=self.obs,
        )
        self._status_reporter = StatusReporter(
            config=self.config,
            ui_lock=self.ui_lock,
            obs=self.obs,
        )

    @asynccontextmanager
    async def ui_session(self, reason: str = ""):
        """
        获取 UI 独占执行权（异步）。
        约定：所有可能改变页面结构/弹窗状态的后台任务（命令、自动处理等）应持有该锁，
        EventManager 的兜底 press_back 也会尊重该锁。
        """
        await self.ui_lock.acquire()
        try:
            if self.logger and reason:
                self.logger.critical(f"[ui_lock] acquired: {reason}")
            yield
        finally:
            if self.logger and reason:
                self.logger.critical(f"[ui_lock] released: {reason}")
            self.ui_lock.release()

    def _start_apps(self):
        """通过Appium server启动QQ Music（Soul app已在创建driver时自动启动）"""
        try:
            print("正在通过Appium server启动QQ Music...")

            # 启动QQ Music
            qq_music_package = self.config["qq_music"]["package_name"]
            qq_music_activity = self.config["qq_music"]["search_activity"]
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
            soul_package = self.config["soul"]["package_name"]
            soul_activity = self.config["soul"]["chat_activity"]
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

        # 设置基本能力
        options.set_capability("platformName", self.config["device"]["platform_name"])
        options.set_capability(
            "platformVersion", self.config["device"]["platform_version"]
        )
        options.set_capability("deviceName", self.config["device"]["name"])
        options.set_capability(
            "automationName", self.config["device"]["automation_name"]
        )
        options.set_capability("noReset", self.config["device"]["no_reset"])

        # 设置应用信息
        options.set_capability("appPackage", self.config["soul"]["package_name"])
        options.set_capability("appActivity", self.config["soul"]["chat_activity"])

        # 优先从环境变量读取，如果没有再从配置文件读取
        appium_host = os.getenv("APPIUM_HOST") or self.config["appium"]["host"]
        appium_port = os.getenv("APPIUM_PORT") or str(self.config["appium"]["port"])

        server_url = f"http://{appium_host}:{appium_port}"
        driver = webdriver.Remote(command_executor=server_url, options=options)
        driver.update_settings({
            "waitForIdleTimeout": 0,  # Don't wait for idle state
            "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
            "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
        })
        return driver

    def register_driver_subscriber(self, component) -> None:
        """Register a component whose .driver reference must track controller.driver."""
        if component is None:
            return
        if not hasattr(self, "_driver_subscribers"):
            self._driver_subscribers = []
        if component in self._driver_subscribers:
            return
        self._driver_subscribers.append(component)
        if hasattr(component, "driver"):
            component.driver = self.driver

    def _notify_driver_subscribers(self, driver) -> None:
        if not hasattr(self, "_driver_subscribers"):
            self._driver_subscribers = []
        for component in list(self._driver_subscribers):
            if not hasattr(component, "driver"):
                continue
            component.driver = driver
            if self.logger:
                self.logger.debug(
                    "更新 %s.driver",
                    component.__class__.__name__,
                )

    def reinitialize_driver(self) -> bool:
        """
        统一的driver重建入口
        所有组件检测到driver失效时必须调用此方法
        """
        # 防止重入（虽然顺序执行，但加个保险）
        if self._is_reinitializing:
            if self.logger:
                self.logger.warning("Driver正在重建中，跳过重复请求")
            return False

        self._is_reinitializing = True
        try:
            if self.logger:
                self.logger.warning("==== 开始重建driver ====")
            self.obs.emit("driver.reinit.start")

            # 1. 关闭旧driver
            try:
                self.driver.quit()
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"关闭旧driver出错: {str(e)}")

            # 2. 等待清理
            time.sleep(1)

            # 3. 创建新driver
            self.driver = self._init_driver()
            if self.logger:
                self.logger.info("新driver创建成功")
            self.obs.emit("driver.reinit.ok")

            # Optimize driver settings
            self.driver.update_settings({
                "waitForIdleTimeout": 0,  # Don't wait for idle state
                "waitForSelectorTimeout": 2000,  # Wait up to 2 seconds for elements
                "waitForPageLoad": 2000  # Wait up to 2 seconds for page load
            })
            self.logger.info("Optimized driver settings")

            # 4. 更新所有订阅组件的driver引用
            self._notify_driver_subscribers(self.driver)

            # 5. 切换回应用
            if self.soul_handler:
                self.soul_handler.key_actions.switch_to_app()

            if self.logger:
                self.logger.info("==== Driver重建完成 ====")
            return True

        except Exception:
            if self.logger:
                self.logger.error(f"Driver重建失败: {traceback.format_exc()}")
            self.obs.emit("driver.reinit.error", level="ERROR", ctx={"error": traceback.format_exc()})
            return False
        finally:
            self._is_reinitializing = False

    def _toggle_console_mode(self):
        """Toggle console mode on Ctrl+P"""
        if not self.in_console_mode:
            self.logger.info("Entering console mode. Press Ctrl+P again to exit...")
            self.in_console_mode = True
        else:
            self.logger.info("Exiting console mode...")
            self.in_console_mode = False

    def _console_input(self):
        """Background thread for console input"""
        while self.is_running:
            try:
                user_input = input("Console> " if self.in_console_mode else "")
                # Process all input, including empty strings (just pressing Enter)
                self.input_queue.put((user_input, "console"))
                self.logger.critical(f"{user_input}")
            except EOFError:
                continue
            except KeyboardInterrupt:
                if self.in_console_mode:
                    self.in_console_mode = False
                    self.logger.info("Exiting console mode...")
                else:
                    self.is_running = False
                break

    def _drain_agent_command_spool(self) -> None:
        self._agent_command_spool.drain()

    def _init_handlers(self):
        """Initialize handlers after driver is ready"""
        try:
            # Initialize handlers using singleton pattern
            self.soul_handler = SoulHandler.initialize(
                self.driver, self.config["soul"], self
            )
            self.register_driver_subscriber(self.soul_handler)
            self.music_handler = QQMusicHandler.initialize(
                self.driver, self.config["qq_music"], self
            )
            self.register_driver_subscriber(self.music_handler)
            self.logger = self.soul_handler.logger

            # Initialize managers using singleton pattern (no parameters needed)
            from ushareiplay.managers.topic_manager import TopicManager
            from ushareiplay.managers.mic_manager import MicManager
            from ushareiplay.managers.music_manager import MusicManager
            from ushareiplay.managers.recovery_manager import RecoveryManager
            from ushareiplay.managers.timer_manager import TimerManager
            from ushareiplay.managers.command_manager import CommandManager
            from ushareiplay.managers.info_manager import InfoManager
            from ushareiplay.managers.seat_manager import SeatManager
            from ushareiplay.managers.admin_manager import AdminManager
            from ushareiplay.managers.keyword_manager import KeywordManager
            from ushareiplay.managers.message_manager import MessageManager
            from ushareiplay.managers.sleep_manager import SleepManager
            from ushareiplay.managers.theme_manager import ThemeManager
            from ushareiplay.managers.title_manager import TitleManager
            from ushareiplay.managers.room_name_manager import RoomNameManager
            from ushareiplay.managers.user_manager import UserManager
            from ushareiplay.state.online_list_scraper import OnlineListScraper
            from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
            from ushareiplay.state.playlist_state import PlaylistState
            from ushareiplay.state.presence_tracker import PresenceTracker
            from ushareiplay.state.room_state import RoomState

            # Initialize managers after handlers are ready
            self.logger.info("创建 manager 实例...")
            self.seat_manager = SeatManager.get_instance(self.soul_handler)

            # Creation is deliberately centralized here. Every other module uses
            # .instance() as a lookup-only API.
            UserManager.initialize()
            SleepManager.initialize(self.config)
            MessageQueue.initialize()
            RecoveryManager.initialize()
            MessageManager.initialize()
            self.message_dispatch = MessageDispatch.initialize()
            self.topic_manager = TopicManager.initialize()
            self.mic_manager = MicManager.initialize()
            self.music_manager = MusicManager.initialize()
            self.register_driver_subscriber(self.music_manager)
            self.recovery_manager = RecoveryManager.instance()
            self.timer_manager = TimerManager.initialize()
            self.command_manager = CommandManager.initialize()
            self.command_manager.controller = self
            self.command_manager.configure_runtime(self.command_runtime_context)
            RoomState.initialize()
            PresenceTracker.initialize()
            PlaylistState.initialize()
            PlaybackBroadcaster.initialize()
            OnlineListScraper.initialize()
            self.info_manager = InfoManager.initialize()
            self.party_manager = PartyManager.initialize()
            self.notice_manager = NoticeManager.initialize()
            RoomNameManager.initialize()
            ThemeManager.initialize()
            TitleManager.initialize()
            AdminManager.initialize()
            KeywordManager.initialize()
            self.post_party_create_automation = PostPartyCreateAutomation(self)
            self._runtime_queue_drainer = RuntimeQueueDrainer(
                handler=self.soul_handler,
                command_manager=self.command_manager,
                send_screen_message=self.message_dispatch.send_screen_message,
                obs=self.obs,
                logger=self.logger,
            )
            self._status_reporter.soul_handler = self.soul_handler
            self._status_reporter.timer_manager = self.timer_manager

            # Initialize command manager with config
            self.logger.info("初始化命令解析器...")
            self.command_manager.initialize_parser(self.config["commands"])

            # Initialize event manager
            self.logger.info("初始化事件管理器...")
            self.event_manager = EventManager.initialize()
            self.event_manager.configure_runtime(self.event_runtime_context)
            self.event_manager.initialize_events()
            self.logger.info("事件管理器初始化完成")

            self.logger.info("Handlers and managers initialized successfully")
            self.logger.info("所有 handlers 和 managers 初始化完成")

        except Exception:
            if self.logger:
                self.logger.error(f"Error initializing handlers: {traceback.format_exc()}")
            raise

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
        from ushareiplay.managers.keyword_manager import KeywordManager
        keyword_manager = KeywordManager.instance()
        await keyword_manager.load_keywords_from_config()
        self.logger.info("关键字系统初始化完成")

        # Start async timer manager (loads from DB, migrates from JSON if needed)
        self.logger.info("初始化定时器管理器...")
        await self.timer_manager.start()
        self.logger.info("定时器管理器初始化完成")

        # Start console input thread
        self.logger.info("启动控制台输入线程...")
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()
        self.logger.info("控制台输入线程已启动")

        self.logger.info("开始主监控循环...")

        paused = False
        while self.is_running:
            try:
                self._drain_agent_command_spool()
                if self._runtime_queue_drainer:
                    await self._runtime_queue_drainer.drain()
                # Check for console input (高优先级，在事件管理器前处理)
                try:
                    while not self.input_queue.empty():
                        item = self.input_queue.get_nowait()
                        if isinstance(item, dict):
                            message = item.get("content", "")
                            input_source = item.get("source", "console")
                            nickname = item.get("nickname", "Console")
                        elif isinstance(item, tuple):
                            message, input_source = item
                            nickname = "Console"
                        else:
                            message, input_source = item, "console"
                            nickname = "Console"
                        # Only send non-empty messages
                        if message.strip():
                            if message == '!stop':
                                paused = not paused
                                self.soul_handler.logger.critical(f'paused: {paused}')
                            elif message == '!timer':
                                if self.timer_manager.is_running():
                                    await self.timer_manager.stop()
                                else:
                                    await self.timer_manager.start()
                                self.soul_handler.logger.critical(f'is_running:{self.timer_manager.is_running()}')
                            elif message == '!dump':
                                # read-only dump of artifacts using existing session
                                try:
                                    await self._dump_readonly_artifacts(reason=input_source)
                                except Exception:
                                    self.obs.emit(
                                        "artifact.dump.error",
                                        level="ERROR",
                                        ctx={"error": traceback.format_exc(), "reason": input_source},
                                    )
                            else:
                                # Allow leading whitespace and spaces after colon.
                                # Keep the queued content in its original (colon-triggered) form.
                                trimmed = message.lstrip()
                                if trimmed and trimmed[0] in (':', '：', '/', '／', '$', '＄') and trimmed[1:].strip():
                                    # Create MessageInfo for queue
                                    from ushareiplay.models.message_info import MessageInfo
                                    message_info = MessageInfo(
                                        content=trimmed,
                                        nickname=nickname
                                    )

                                    # Add message to queue
                                    message_queue = MessageQueue.instance()
                                    await message_queue.put_message(message_info)
                                    self.obs.emit(
                                        "queue.enqueue",
                                        ctx={"source": input_source, "content": message_info.content, "nickname": message_info.nickname},
                                    )
                                    self.logger.info(f"{input_source} message added to queue: {message}")
                                else:
                                    self.message_dispatch.send_screen_message(message)

                except queue.Empty:
                    pass

                if paused:
                    continue

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

        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                if self.logger:
                    self.logger.warning("Failed to close Appium driver during shutdown")
