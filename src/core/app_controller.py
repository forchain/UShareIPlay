import asyncio
import os
import queue
import re
import threading
import time
import traceback
from contextlib import asynccontextmanager

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import WebDriverException, StaleElementReferenceException

from .message_queue import MessageQueue
from .singleton import Singleton
from ..core.db_service import DBHelper
from ..handlers.qq_music_handler import QQMusicHandler
from ..handlers.soul_handler import SoulHandler
from ..managers.event_manager import EventManager
from ..managers.notice_manager import NoticeManager
from ..managers.party_manager import PartyManager


class AppController(Singleton):
    def __init__(self, config):
        self.config = config

        # 先创建主driver（会自动启动Soul app）
        self.driver = self._init_driver()

        # 使用主driver启动其他应用
        self._start_apps()
        self.input_queue = queue.Queue()
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
                self.input_queue.put(user_input)
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

    def _init_handlers(self):
        """Initialize handlers after driver is ready"""
        try:
            print("开始初始化 handlers...")

            # Initialize handlers using singleton pattern
            print("初始化 SoulHandler...")
            print(
                f"SoulHandler 参数: driver={type(self.driver)}, config={self.config['soul']}"
            )
            self.soul_handler = SoulHandler.instance(
                self.driver, self.config["soul"], self
            )
            print("SoulHandler 初始化完成")
            print("初始化 QQMusicHandler...")
            print(
                f"QQMusicHandler 参数: driver={type(self.driver)}, config={self.config['qq_music']}"
            )
            self.music_handler = QQMusicHandler.instance(
                self.driver, self.config["qq_music"], self
            )
            print("QQMusicHandler 初始化完成")
            self.logger = self.soul_handler.logger
            print("Handlers 初始化完成")

            # Initialize managers using singleton pattern (no parameters needed)
            from ..managers.topic_manager import TopicManager
            from ..managers.mic_manager import MicManager
            from ..managers.music_manager import MusicManager
            from ..managers.recovery_manager import RecoveryManager
            from ..managers.timer_manager import TimerManager
            from ..managers.command_manager import CommandManager
            from ..managers.info_manager import InfoManager
            from ..managers.seat_manager import init_seat_manager
            from ..managers.notice_manager import NoticeManager

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

    async def _async_non_ui_operations_loop(self):
        """
        异步后台任务，定期执行非 UI 操作
        使用 asyncio.to_thread() 将同步操作放到线程池执行
        """
        while self.is_running:
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                self.logger.info("Non-UI operations loop cancelled")
                break
            except Exception:
                self.logger.error(
                    f"Error in async non-UI operations loop: {traceback.format_exc()}"
                )
                # 出错后等待一段时间再继续
                await asyncio.sleep(2)

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
        from ..managers.keyword_manager import KeywordManager
        keyword_manager = KeywordManager.instance()
        await keyword_manager.load_keywords_from_config()
        print("关键字系统初始化完成")

        # Initialize timer manager with initial timers from config
        print("初始化定时器管理器...")
        self.command_manager.initialize_timer_manager(self.config)
        # Start async timer manager
        await self.timer_manager.start()
        print("定时器管理器初始化完成")

        # Start console input thread
        print("启动控制台输入线程...")
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()
        print("控制台输入线程已启动")

        # Start non-UI operations background task
        print("启动非 UI 操作后台任务...")
        self._non_ui_task = asyncio.create_task(self._async_non_ui_operations_loop())
        print("非 UI 操作后台任务已启动")

        # Check if party already exists and seat owner if needed
        print("检查派对状态并尝试给群主找座位...")
        try:
            if self.recovery_manager.is_normal_state():
                self.logger.info("检测到派对已存在，尝试给群主找座位")
                from ..managers.seat_manager import seat_manager

                result = seat_manager.seating.find_owner_seat()
                if "success" in result:
                    self.logger.info("服务器启动时成功给群主找到座位")
                else:
                    self.logger.warning(
                        f"服务器启动时给群主找座位失败: {result.get('error', 'Unknown error')}"
                    )
            else:
                self.logger.info("派对不存在或状态异常，跳过座位检查")
        except Exception as e:
            self.logger.error(f"服务器启动时检查座位出错: {str(e)}")
        print("座位检查完成")

        print("开始主监控循环...")

        paused = False
        while self.is_running:
            try:
                # Check for console input (高优先级，在事件管理器前处理)
                try:
                    while not self.input_queue.empty():
                        message = self.input_queue.get_nowait()
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
                            else:
                                pattern = r'(:.+)'
                                command = re.match(pattern, message)
                                if command:
                                    # Create MessageInfo for queue
                                    from ..models.message_info import MessageInfo
                                    message_info = MessageInfo(
                                        content=command.group(1).strip(),
                                        nickname="Console"
                                    )

                                    # Add message to queue
                                    message_queue = MessageQueue.instance()
                                    await message_queue.put_message(message_info)
                                    self.logger.info(f"Console message added to queue: {message}")
                                else:
                                    self.soul_handler.send_message(message)

                except queue.Empty:
                    pass

                if paused:
                    continue

                # 获取 page_source（一次性获取，供事件管理器和其他检测使用）
                if page_source := self.event_manager.get_page_source():
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
