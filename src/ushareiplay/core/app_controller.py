import asyncio
import os
import queue
import re
import threading
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import WebDriverException, StaleElementReferenceException

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.db_service import DBHelper
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
        self.obs.emit("driver.init.start")
        self.driver = self._init_driver()
        self.obs.emit("driver.init.ok")

        # 使用主driver启动其他应用
        self._start_apps()
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

        # Initialize database helper
        self.db_helper = DBHelper()

        # Initialize managers (will be done after handlers are initialized)
        self.seat_manager = None
        self.recovery_manager = None
        self.music_manager = None
        self.event_manager = None

        # Non-UI operations task
        self._non_ui_task = None

        # 全局 UI 互斥锁：
        # 用于防止后台事件循环（如未知页面自动 back）与命令/UI任务并发操作同一界面。
        # 注意：锁只在 async 逻辑中使用；同步 handler 方法不直接 await。
        self.ui_lock: asyncio.Lock = asyncio.Lock()

        # Driver重建防护标志
        self._is_reinitializing = False

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

            # 4. 更新所有组件的driver引用
            if self.soul_handler:
                self.soul_handler.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 soul_handler.driver")

            if self.music_handler:
                self.music_handler.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 music_handler.driver")

            # 5. 更新music_manager（关键修复！）
            if hasattr(self, "music_manager") and self.music_manager:
                self.music_manager.driver = self.driver
                if self.logger:
                    self.logger.debug("更新 music_manager.driver")

            # 6. 切换回应用
            if self.soul_handler:
                self.soul_handler.switch_to_app()

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
            print("\nEntering console mode. Press Ctrl+P again to exit...")
            self.in_console_mode = True
        else:
            print("\nExiting console mode...")
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
                    print("\nExiting console mode...")
                else:
                    self.is_running = False
                break

    def _drain_agent_command_spool(self) -> None:
        """
        Read commands injected by external Agent runners.

        This is intentionally file-based so a runner can inject into a reused
        process without owning the process stdin or opening a second Appium
        session. Commands still flow through the same console queue path.
        """
        try:
            self.agent_command_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.agent_command_dir.glob("*.cmd")):
                try:
                    message = path.read_text(encoding="utf-8").strip()
                    path.unlink(missing_ok=True)
                except Exception:
                    if self.obs:
                        self.obs.emit(
                            "agent.inject.error",
                            level="ERROR",
                            ctx={"path": str(path), "error": traceback.format_exc()},
                        )
                    continue
                if message:
                    self.input_queue.put((message, "agent_spool"))
                    if self.obs:
                        self.obs.emit("agent.inject.received", ctx={"source": "agent_spool", "content": message})
        except Exception:
            if self.obs:
                self.obs.emit("agent.inject.error", level="ERROR", ctx={"error": traceback.format_exc()})

    def _init_handlers(self):
        """Initialize handlers after driver is ready"""
        try:
            # Initialize handlers using singleton pattern
            self.soul_handler = SoulHandler.instance(
                self.driver, self.config["soul"], self
            )
            self.music_handler = QQMusicHandler.instance(
                self.driver, self.config["qq_music"], self
            )
            self.logger = self.soul_handler.logger

            # Initialize managers using singleton pattern (no parameters needed)
            from ushareiplay.managers.topic_manager import TopicManager
            from ushareiplay.managers.mic_manager import MicManager
            from ushareiplay.managers.music_manager import MusicManager
            from ushareiplay.managers.recovery_manager import RecoveryManager
            from ushareiplay.managers.timer_manager import TimerManager
            from ushareiplay.managers.command_manager import CommandManager
            from ushareiplay.managers.info_manager import InfoManager
            from ushareiplay.managers.seat_manager import init_seat_manager
            from ushareiplay.managers.notice_manager import NoticeManager

            # Initialize managers after handlers are ready
            print("创建 manager 实例...")
            self.seat_manager = init_seat_manager(self.soul_handler)
            self.topic_manager = TopicManager.instance()
            self.mic_manager = MicManager.instance()
            self.music_manager = MusicManager.instance()
            self.recovery_manager = RecoveryManager.instance()
            self.timer_manager = TimerManager.instance()
            self.command_manager = CommandManager.instance()
            self.info_manager = InfoManager.instance()
            self.party_manager = PartyManager.instance()
            self.notice_manager = NoticeManager.instance()

            # Initialize command manager with config
            print("初始化命令解析器...")
            self.command_manager.initialize_parser(self.config["commands"])

            # Initialize event manager
            print("初始化事件管理器...")
            self.event_manager = EventManager.instance()
            self.event_manager.initialize()
            print("事件管理器初始化完成")

            self.logger.info("Handlers and managers initialized successfully")
            print("所有 handlers 和 managers 初始化完成")

        except Exception:
            print(f"Error initializing handlers: {traceback.format_exc()}")
            raise

    async def start_monitoring(self):
        error_count = 0

        # Initialize handlers first
        print("开始启动监控...")
        self._init_handlers()

        # Load all command modules using CommandManager
        print("加载命令模块...")
        self.command_manager.load_all_commands()
        self.logger.info("All command modules loaded")
        print("命令模块加载完成")

        # Initialize keyword system and load keywords from config
        print("初始化关键字系统...")
        from ushareiplay.managers.keyword_manager import KeywordManager
        keyword_manager = KeywordManager.instance()
        await keyword_manager.load_keywords_from_config()
        print("关键字系统初始化完成")

        # Start async timer manager (loads from DB, migrates from JSON if needed)
        print("初始化定时器管理器...")
        await self.timer_manager.start()
        print("定时器管理器初始化完成")

        # Start console input thread
        print("启动控制台输入线程...")
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()
        print("控制台输入线程已启动")

        print("开始主监控循环...")

        paused = False
        while self.is_running:
            try:
                self._drain_agent_command_spool()
                # Check for console input (高优先级，在事件管理器前处理)
                try:
                    while not self.input_queue.empty():
                        item = self.input_queue.get_nowait()
                        if isinstance(item, tuple):
                            message, input_source = item
                        else:
                            message, input_source = item, "console"
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
                                pattern = r'([:：].+)'
                                command = re.match(pattern, message)
                                if command:
                                    # Create MessageInfo for queue
                                    from ushareiplay.models.message_info import MessageInfo
                                    message_info = MessageInfo(
                                        content=command.group(1).strip(),
                                        nickname="Console" if input_source == "console" else "Agent"
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
                                    self.soul_handler.send_message(message)

                except queue.Empty:
                    pass

                if paused:
                    continue

                # 获取 page_source（一次性获取，供事件管理器和其他检测使用）
                page_source = self.event_manager.get_page_source()
                if not page_source:
                    # 切回/启动瞬间 page_source 偶尔为空，做一次轻量重试以减少误判窗口
                    await asyncio.sleep(0.2)
                    page_source = self.event_manager.get_page_source()

                if page_source:
                    await self._update_status_from_page_source(page_source)
                    await self.event_manager.process_events(page_source)

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
                    print("\nEntering console mode. Press Ctrl+C to exit...")
                    self.in_console_mode = True
                else:
                    print("\nStopping the monitoring...")
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

    async def _update_status_from_page_source(self, page_source: str) -> None:
        # Minimal, low-cost snapshot. More detailed classification can be expanded later.
        try:
            from ushareiplay.managers.event_manager import EventManager

            event_manager = EventManager.instance()
            pkgs = event_manager._packages_from_page_source(page_source)  # best-effort internal helper
            soul_pkg = event_manager._soul_package_name()
            qq_pkg = (self.config.get("qq_music", {}) or {}).get("package_name", "com.tencent.qqmusic")
            launchers = set(event_manager._launcher_packages())

            foreground_app = "Unknown"
            if pkgs:
                if soul_pkg in pkgs:
                    foreground_app = "Soul"
                elif qq_pkg in pkgs:
                    foreground_app = "QQMusic"
                elif pkgs & launchers:
                    foreground_app = "Launcher"

            anchors = []
            soul_elements = (self.config.get("soul", {}) or {}).get("elements", {}) or {}
            for k in ("message_content", "input_box_entry", "input_box"):
                v = soul_elements.get(k)
                if v and isinstance(v, str) and v in page_source:
                    anchors.append(k)

            ui_lock_state = "locked" if (self.ui_lock and self.ui_lock.locked()) else "unlocked"
            queue_size = MessageQueue.instance().get_queue_size()

            soul_ui_state = "Unknown"
            if foreground_app == "Soul":
                if "message_content" in anchors:
                    soul_ui_state = "InChatReady"
                else:
                    soul_ui_state = "InUnknownPage"

            status = {
                "foreground_app": foreground_app,
                "soul_ui_state": soul_ui_state,
                "qqmusic_ui_state": "Unknown",
                "anchors": anchors,
                "pipeline": {"ui_lock": ui_lock_state, "queue_size": queue_size},
                "business": {
                    "party_id_current": getattr(self.soul_handler, "party_id", None) if self.soul_handler else None,
                    "party_id_target": (self.config.get("soul", {}) or {}).get("default_party_id"),
                    "timers_running": bool(getattr(self, "timer_manager", None) and self.timer_manager.is_running()),
                    "playback_info_summary": None,
                },
            }
            self.obs.write_status(status)
            self.obs.emit("state.snapshot", ctx={"foreground_app": foreground_app, "anchors": anchors})
            if foreground_app == "Soul" and soul_ui_state == "InChatReady":
                self.obs.emit("state.ready", ctx={"name": "CommandReady", "anchors": anchors, "foreground_app": foreground_app})
        except Exception:
            self.obs.emit("state.snapshot.error", level="ERROR", ctx={"error": traceback.format_exc()})

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
