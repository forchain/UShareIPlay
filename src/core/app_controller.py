import asyncio
import queue
import threading
import traceback

from appium import webdriver
from appium.options.common import AppiumOptions
from selenium.common import WebDriverException, StaleElementReferenceException

from .singleton import Singleton
from ..core.db_service import DBHelper
from ..handlers.qq_music_handler import QQMusicHandler
from ..handlers.soul_handler import SoulHandler
from ..managers.seat_manager import init_seat_manager


class AppController(Singleton):
    def __init__(self, config):
        self.config = config

        # 在初始化driver之前先启动应用
        self._start_apps()

        self.driver = self._init_driver()
        self.input_queue = queue.Queue()
        self.is_running = True
        self.in_console_mode = False
        self.player_name = 'Outlier'

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

    def _start_apps(self):
        """在初始化driver之前启动Soul app和QQ Music"""
        try:
            import subprocess
            import time

            print("正在启动应用...")

            # 启动QQ Music
            qq_music_package = self.config['qq_music']['package_name']
            print(f"正在启动QQ Music: {qq_music_package}")

            # 使用adb启动QQ Music
            subprocess.run([
                'adb', '-s', self.config['device']['name'],
                'shell', 'am', 'start', '-n',
                f"{qq_music_package}/{self.config['qq_music']['search_activity']}"
            ], check=True)

            # 启动Soul app
            soul_package = self.config['soul']['package_name']
            print(f"正在启动Soul app: {soul_package}")

            # 使用adb启动Soul app
            subprocess.run([
                'adb', '-s', self.config['device']['name'],
                'shell', 'am', 'start', '-n',
                f"{soul_package}/{self.config['soul']['chat_activity']}"
            ], check=True)

            print("应用启动完成")

        except subprocess.CalledProcessError as e:
            print(f"启动应用失败: {str(e)}")
            raise
        except Exception as e:
            print(f"启动应用时发生错误: {str(e)}")
            raise

    def _init_driver(self):
        options = AppiumOptions()

        # 设置基本能力
        options.set_capability('platformName', self.config['device']['platform_name'])
        options.set_capability('platformVersion', self.config['device']['platform_version'])
        options.set_capability('deviceName', self.config['device']['name'])
        options.set_capability('automationName', self.config['device']['automation_name'])
        options.set_capability('noReset', self.config['device']['no_reset'])

        # 设置应用信息
        options.set_capability('appPackage', self.config['soul']['package_name'])
        options.set_capability('appActivity', self.config['soul']['chat_activity'])

        server_url = f"http://{self.config['appium']['host']}:{self.config['appium']['port']}"
        return webdriver.Remote(command_executor=server_url, options=options)

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
            print(f"SoulHandler 参数: driver={type(self.driver)}, config={self.config['soul']}")
            self.soul_handler = SoulHandler.instance(self.driver, self.config['soul'], self)
            print("SoulHandler 初始化完成")
            print("初始化 QQMusicHandler...")
            print(f"QQMusicHandler 参数: driver={type(self.driver)}, config={self.config['qq_music']}")
            self.music_handler = QQMusicHandler.instance(self.driver, self.config['qq_music'], self)
            print("QQMusicHandler 初始化完成")
            self.logger = self.soul_handler.logger
            print("Handlers 初始化完成")

            # Initialize managers after handlers are ready
            print("初始化 seat_manager...")
            self.seat_manager = init_seat_manager(self.soul_handler)

            # Initialize managers using singleton pattern (no parameters needed)
            print("初始化其他 managers...")
            from ..managers.topic_manager import TopicManager
            from ..managers.mic_manager import MicManager
            from ..managers.music_manager import MusicManager
            from ..managers.recovery_manager import RecoveryManager
            from ..managers.timer_manager import TimerManager
            from ..managers.command_manager import CommandManager

            print("创建 manager 实例...")
            self.topic_manager = TopicManager.instance()
            self.mic_manager = MicManager.instance()
            self.music_manager = MusicManager.instance()
            self.recovery_manager = RecoveryManager.instance()
            self.timer_manager = TimerManager.instance()
            self.command_manager = CommandManager.instance()

            # Initialize command manager with config
            print("初始化命令解析器...")
            self.command_manager.initialize_parser(self.config['commands'])

            self.logger.info("Handlers and managers initialized successfully")
            print("所有 handlers 和 managers 初始化完成")

        except Exception as e:
            print(f"Error initializing handlers: {traceback.format_exc()}")
            raise

    async def _process_queue_messages(self):
        """Process messages from the async queue (timer messages, etc.)"""
        try:
            from ..core.message_queue import MessageQueue
            message_queue = MessageQueue.instance()

            # Get all messages from queue
            queue_messages = await message_queue.get_all_messages()
            if queue_messages:
                self.logger.info(f"Processing {len(queue_messages)} queue messages")

                # Process all messages through CommandManager
                response = await self.command_manager.handle_message_commands(queue_messages)
                if response:
                    self.soul_handler.send_message(response)

        except Exception as e:
            self.logger.error(f"Error processing queue messages: {str(e)}")

    async def start_monitoring(self):
        response = None
        last_info = None
        error_count = 0

        # Initialize handlers first
        print("开始启动监控...")
        self._init_handlers()

        # Load all command modules using CommandManager
        print("加载命令模块...")
        self.command_manager.load_all_commands()
        self.logger.info("All command modules loaded")
        print("命令模块加载完成")

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

        print("开始主监控循环...")

        while self.is_running:
            try:
                # 异常检测和恢复 - 在每次循环的最开始执行
                recovery_performed = self.recovery_manager.check_and_recover()
                if recovery_performed:
                    # 如果执行了恢复操作，等待一下让界面稳定
                    await asyncio.sleep(1)
                    continue

                # Check for console input
                try:
                    while not self.input_queue.empty():
                        message = self.input_queue.get_nowait()
                        # Only send non-empty messages
                        if message.strip():
                            self.soul_handler.send_message(message)
                except queue.Empty:
                    pass

                # Update all commands
                self.command_manager.update_commands()

                info = self.music_handler.get_playback_info()
                # ignore state
                info['state'] = None
                if info != last_info:
                    last_info = info

                    # 只有在歌曲信息发生变化时才处理
                    # 检查歌曲信息是否有效
                    if 'error' not in info and all(key in info for key in ['song', 'singer', 'album']):
                        # 检查是否需要跳过低质量歌曲
                        song_skipped = self.music_handler.handle_song_quality_check(info)

                        # 只有在没有跳过歌曲的情况下才发送播放消息
                        if not song_skipped:
                            self.soul_handler.send_message(
                                f"Playing {info['song']} by {info['singer']} in {info['album']}")
                    else:
                        # 如果歌曲信息无效，记录错误但不中断监控
                        if 'error' in info:
                            if info.get('session_lost', False):
                                self.logger.warning("Appium session lost, skipping music monitoring temporarily")
                                # 可以在这里添加重新连接逻辑
                            else:
                                self.logger.warning(f"Failed to get song info: {info['error']}")
                        else:
                            self.logger.warning("Song info missing required keys")

                # Process queue messages (timer messages, etc.)
                await self._process_queue_messages()

                # Monitor Soul messages
                messages = await self.soul_handler.message_manager.get_latest_message()
                if response:
                    self.soul_handler.send_message(response)
                    response = None

                if messages == 'ABNORMAL_STATE':
                    # Unable to access message list - abnormal state
                    self.recovery_manager.mark_abnormal_state()
                elif messages:
                    # New messages found - process them
                    response = await self.command_manager.handle_message_commands(messages)
                else:
                    await asyncio.sleep(1)

                # clear error once back to normal
                error_count = 0
                if self.soul_handler.error_count > 9:
                    self.soul_handler.log_error(
                        f'[start_monitoring]too many errors, try to rerun, traceback: {traceback.format_exc()}')
                    return False
            except KeyboardInterrupt:
                if not self.in_console_mode:
                    print("\nEntering console mode. Press Ctrl+C to exit...")
                    self.in_console_mode = True
                else:
                    print("\nStopping the monitoring...")
                    self.is_running = False
                    return True
            except StaleElementReferenceException as e:
                self.soul_handler.log_error(f'[start_monitoring]stale element, traceback: {traceback.format_exc()}')
            except WebDriverException as e:
                self.soul_handler.log_error(f'[start_monitoring]unknown error, traceback: {traceback.format_exc()}')
                error_count += 1
                if error_count > 9:
                    self.is_running = False
                    return False
        return None

    async def stop(self):
        """Stop the application"""
        self.is_running = False
        # Stop async timer manager
        await self.timer_manager.stop()
        self.logger.info("Application stopped")
