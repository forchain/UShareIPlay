from appium import webdriver
from selenium.common import WebDriverException, StaleElementReferenceException
from appium.options.common import AppiumOptions
from ..soul.soul_handler import SoulHandler
from ..music.qq_music_handler import QQMusicHandler
from ..core.command_parser import CommandParser
import time
import traceback
import importlib
from pathlib import Path
import sys
import threading
import queue
from ..core.db_service import DBHelper
from ..managers.seat_manager import init_seat_manager
from ..managers.recovery_manager import RecoveryManager
from .singleton import Singleton


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
        
        # Get lyrics formatter tags from lyrics command config
        lyrics_tags = next(
            (cmd.get('tags', []) for cmd in config['commands'] if cmd['prefix'] == 'lyrics'),
            []
        )

        # Initialize handlers using singleton pattern (delayed initialization)
        self.soul_handler = None
        self.music_handler = None
        self.logger = None

        # Initialize command parser
        self.command_parser = CommandParser(config['commands'])

        self.commands_path = Path(__file__).parent.parent / 'commands'
        self.command_modules = {}  # Cache for loaded command modules

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

    def _load_command_module(self, command):
        """Load command module dynamically"""
        try:
            if command in self.command_modules:
                return self.command_modules[command]
                
            module_path = (Path(__file__).parent.parent / 'commands' / f"{command}.py").resolve()
            if not module_path.exists():
                if self.logger:
                    self.logger.error(f'module path not exists, {module_path}')
                else:
                    print(f'module path not exists, {module_path}')
                return None
                
            package_name = f"src.commands.{command}"
            spec = importlib.util.spec_from_file_location(package_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)

            if not module:
                self.soul_handler.logger.error('Command module failed to load')
                return None

            if not hasattr(module, 'command'):
                self.soul_handler.logger.error('Command module does not have command')
                return None

            # Create command instance
            if not hasattr(module, 'create_command'):
                self.soul_handler.logger.error('Command module does not have create_command')
                return None

            module.command = module.create_command(self)
            self.command_modules[command] = module
            return module
            
        except Exception as e:
            self.soul_handler.log_error(f"Error loading command module {command}: {traceback.format_exc()}")
            return None

    def _update_commands(self):
        """Update all loaded commands"""
        for module in self.command_modules.values():
            try:
                if hasattr(module, 'command'):
                    module.command.update()
            except Exception as e:
                self.soul_handler.log_error(f"Error updating command {module.__name__}: {str(e)}")

    def _check_command(self, command):
        # Try to load command module
        module = self._load_command_module(command)
        return module.command if module else None

    async def _process_command(self, command, message_info, command_info):
        """Process command using module if available
        Args:
            message_info: MessageInfo object
            command_info: dict containing command details
        Returns:
            str: Response message
        """
        try:
            parameters= command_info['parameters']
            result = await command.process(message_info, parameters)
            
            if 'error' in result:
                res = command_info['error_template'].format(
                    error=result['error'],
                    user=message_info.nickname,
                )
            else:
                res = f'{command_info['response_template'].format(**result)} @{message_info.nickname}'
            return res
        except Exception as e:
            self.soul_handler.log_error(f"Error processing command {command_info}: {traceback.format_exc()}")
            return f"Error processing command {command_info}"

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

    def _load_all_commands(self):
        """Load all command modules from commands directory
        Returns:
            dict: Loaded command modules
        """
        try:
            # Get all .py files in commands directory
            command_files = [f.stem for f in self.commands_path.glob('*.py') 
                            if f.is_file() and not f.stem.startswith('__')]
            
            self.logger.info(f"Found command files: {command_files}")
            
            # Load each command module
            for command in command_files:
                try:
                    module = self._load_command_module(command)
                    if module:
                        if self.logger:
                            self.logger.info(f"Loaded command module: {command}")
                        else:
                            print(f"Loaded command module: {command}")
                    else:
                        if self.logger:
                            self.logger.error(f"Failed to load command module: {command}")
                        else:
                            print(f"Failed to load command module: {command}")
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error loading command {command}: {traceback.format_exc()}")
                    else:
                        print(f"Error loading command {command}: {traceback.format_exc()}")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error loading commands: {traceback.format_exc()}")
            else:
                print(f"Error loading commands: {traceback.format_exc()}")

    def _init_timer_manager(self):
        """Initialize timer manager with initial timers from config"""
        try:
            # Check if timer command is loaded
            if hasattr(self, 'timer_command') and hasattr(self.timer_command, 'timer_manager'):
                timer_manager = self.timer_command.timer_manager
                
                # Load initial timers from config (force update to ensure config values are used)
                initial_timers = self.config.get('soul', {}).get('initial_timers', [])
                if initial_timers:
                    timer_manager.load_initial_timers(initial_timers, force_update=True)
                    self.logger.info(f"Loaded/Updated {len(initial_timers)} initial timers from config")
                else:
                    self.logger.info("No initial timers configured")
            else:
                self.logger.warning("Timer command not loaded, skipping timer initialization")
                
        except Exception as e:
            self.logger.error(f"Error initializing timer manager: {traceback.format_exc()}")


    def _init_handlers(self):
        """Initialize handlers after driver is ready"""
        try:
            # Initialize handlers using singleton pattern
            self.soul_handler = SoulHandler.instance(self.driver, self.config['soul'], self)
            self.music_handler = QQMusicHandler.instance(self.driver, self.config['qq_music'], self)
            self.logger = self.soul_handler.logger
            
            # Initialize managers after handlers are ready
            self.seat_manager = init_seat_manager(self.soul_handler)
            self.recovery_manager = RecoveryManager(self.soul_handler)
            
            self.logger.info("Handlers and managers initialized successfully")
            
        except Exception as e:
            print(f"Error initializing handlers: {traceback.format_exc()}")
            raise

    async def start_monitoring(self):
        response = None
        lyrics = None
        last_info = None
        error_count = 0
        
        # Initialize handlers first
        self._init_handlers()
        
        # Load all command modules
        self._load_all_commands()
        self.logger.info("All command modules loaded")
        
        # Initialize timer manager with initial timers from config
        self._init_timer_manager()
        
        # Start console input thread
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()

        while self.is_running:
            try:
                # 异常检测和恢复 - 在每次循环的最开始执行
                recovery_performed = self.recovery_manager.check_and_recover()
                if recovery_performed:
                    # 如果执行了恢复操作，等待一下让界面稳定
                    time.sleep(1)
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
                self._update_commands()
                
                info = self.music_handler.get_playback_info()
                # ignore state
                info['state'] = None
                if info != last_info:
                    last_info = info
                    if self.music_handler.list_mode == 'singer':
                        if info['song'].endswith('(Live)'):
                            if self.music_handler.no_skip > 0:
                                self.music_handler.no_skip -= 1
                            else:
                                self.music_handler.skip_song()
                    if 'DJ' in info['song'] or 'Remix' in info['song']:
                        self.music_handler.skip_song()

                    self.soul_handler.send_message(f"Playing {info['song']} by {info['singer']} in {info['album']}")

                # Monitor Soul messages
                messages = await self.soul_handler.message_manager.get_latest_message()
                # get messages in advance to avoid being floored by responses
                if lyrics:
                    self.soul_handler.send_message(lyrics)
                    lyrics = None
                if response:
                    self.soul_handler.send_message(response)
                    response = None
                if messages:
                    # Iterate through message info objects
                    for msg_id, message_info in messages.items():
                        if self.command_parser.is_valid_command(message_info.content):
                            command_info = self.command_parser.parse_command(message_info.content)
                            if command_info:
                                # Handle different commands using match-case
                                cmd = command_info['prefix']

                                self.soul_handler.send_message(
                                    f'Processing :{cmd} command @{message_info.nickname}')

                                command = self._check_command(cmd)
                                if command:
                                    response = await self._process_command(command, message_info, command_info)
                                else:
                                    self.soul_handler.log_error(f"Unknown command: {cmd}")
                # Check KTV lyrics if mode is enabled
                if self.music_handler.ktv_mode:
                    res = self.music_handler.check_ktv_lyrics()
                    if 'error' in res:
                        lyrics = f'stopped KTV mode for {res["error"]}'
                    else:
                        lyrics = res['lyrics']
                else:
                    time.sleep(1)

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
