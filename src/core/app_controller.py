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


class AppController:
    def __init__(self, config):
        self.config = config
        
        # 在初始化driver之前先启动应用
        self._start_apps()
        
        self.driver = self._init_driver()
        self.input_queue = queue.Queue()
        self.is_running = True
        self.in_console_mode = False
        self.player_name = 'Outlier'
        
        # Connection recovery tracking
        self.connection_error_count = 0
        recovery_config = config.get('connection_recovery', {})
        self.max_connection_errors = recovery_config.get('max_errors', 3)
        self.last_driver_init_time = time.time()
        self.driver_reinit_cooldown = recovery_config.get('cooldown_seconds', 30)
        self.adb_timeout = recovery_config.get('adb_timeout', 20)
        self.app_start_wait = recovery_config.get('app_start_wait', 5)
        
        # Get lyrics formatter tags from lyrics command config
        lyrics_tags = next(
            (cmd.get('tags', []) for cmd in config['commands'] if cmd['prefix'] == 'lyrics'),
            []
        )

        # Initialize handlers
        self.soul_handler = SoulHandler(self.driver, config['soul'], self)
        self.music_handler = QQMusicHandler(self.driver, config['qq_music'], self)
        self.logger = self.soul_handler.logger

        # Initialize command parser
        self.command_parser = CommandParser(config['commands'])

        self.commands_path = Path(__file__).parent.parent / 'commands'
        self.command_modules = {}  # Cache for loaded command modules

        # Initialize database helper
        self.db_helper = DBHelper()

        # Initialize managers
        self.seat_manager = init_seat_manager(self.soul_handler)
        self.recovery_manager = RecoveryManager(self.soul_handler)

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

    def _check_adb_connection(self) -> bool:
        """检查 ADB 连接状态"""
        try:
            import subprocess
            result = subprocess.run([
                'adb', 'devices'
            ], capture_output=True, text=True, timeout=10)
            
            device_name = self.config['device']['name']
            return device_name in result.stdout and 'device' in result.stdout
        except Exception as e:
            self.logger.error(f"Failed to check ADB connection: {str(e)}")
            return False

    def _reconnect_adb(self) -> bool:
        """重新连接 ADB"""
        try:
            import subprocess
            device_name = self.config['device']['name']
            
            # If it's a network device (contains :), try to reconnect
            if ':' in device_name:
                self.logger.info(f"Attempting to reconnect ADB to {device_name}")
                
                # Kill and restart ADB server
                subprocess.run(['adb', 'kill-server'], timeout=10)
                time.sleep(2)
                subprocess.run(['adb', 'start-server'], timeout=10)
                time.sleep(2)
                
                # Reconnect to device
                result = subprocess.run([
                    'adb', 'connect', device_name
                ], capture_output=True, text=True, timeout=self.adb_timeout)
                
                if 'connected' in result.stdout.lower():
                    self.logger.info(f"Successfully reconnected to {device_name}")
                    return True
                else:
                    self.logger.error(f"Failed to reconnect to {device_name}: {result.stdout}")
                    return False
            else:
                # For USB devices, just restart ADB
                subprocess.run(['adb', 'kill-server'], timeout=10)
                time.sleep(2)
                subprocess.run(['adb', 'start-server'], timeout=10)
                time.sleep(3)
                return self._check_adb_connection()
                
        except Exception as e:
            self.logger.error(f"Error during ADB reconnection: {str(e)}")
            return False

    def _reinitialize_driver(self) -> bool:
        """重新初始化 Appium driver"""
        current_time = time.time()
        
        # Check cooldown period
        if current_time - self.last_driver_init_time < self.driver_reinit_cooldown:
            self.logger.warning(f"Driver reinitialization in cooldown, waiting...")
            return False
            
        try:
            self.logger.warning("Attempting to reinitialize Appium driver...")
            
            # 1. Clean up old driver
            if hasattr(self, 'driver') and self.driver:
                try:
                    self.driver.quit()
                except:
                    pass  # Ignore errors when quitting broken driver
            
            # 2. Check and fix ADB connection
            if not self._check_adb_connection():
                self.logger.warning("ADB connection lost, attempting to reconnect...")
                if not self._reconnect_adb():
                    self.logger.error("Failed to reconnect ADB")
                    return False
                time.sleep(3)  # Wait for ADB to stabilize
            
            # 3. Restart applications
            self._start_apps()
            time.sleep(self.app_start_wait)  # Wait for apps to start
            
            # 4. Initialize new driver
            self.driver = self._init_driver()
            self.last_driver_init_time = current_time
            
            # 5. Update driver reference in handlers
            self.soul_handler.driver = self.driver
            self.music_handler.driver = self.driver
            
            # 6. Reset error counters
            self.connection_error_count = 0
            self.soul_handler.error_count = 0
            self.music_handler.error_count = 0
            
            self.logger.info("Successfully reinitialized Appium driver")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reinitialize driver: {str(e)}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _is_connection_error(self, error: Exception) -> bool:
        """判断是否为连接相关错误"""
        error_str = str(error).lower()
        connection_keywords = [
            'socket hang up',
            'could not proxy command',
            'connection refused',
            'connection reset',
            'broken pipe',
            'network is unreachable',
            'timeout',
            'connection aborted',
            'remote end closed connection'
        ]
        return any(keyword in error_str for keyword in connection_keywords)

    def _handle_connection_error(self, error: Exception) -> bool:
        """处理连接错误"""
        self.connection_error_count += 1
        self.logger.error(f"Connection error #{self.connection_error_count}: {str(error)}")
        
        if self.connection_error_count >= self.max_connection_errors:
            self.logger.warning(f"Reached max connection errors ({self.max_connection_errors}), attempting driver reinitialization...")
            
            if self._reinitialize_driver():
                self.logger.info("Driver reinitialization successful, continuing...")
                return True
            else:
                self.logger.error("Driver reinitialization failed, giving up...")
                return False
        else:
            # Wait a bit before retrying
            wait_time = min(2 ** self.connection_error_count, 30)  # Exponential backoff, max 30s
            self.logger.info(f"Waiting {wait_time} seconds before retry...")
            time.sleep(wait_time)
            return True

    def _load_command_module(self, command):
        """Load command module dynamically"""
        try:
            if command in self.command_modules:
                return self.command_modules[command]
                
            module_path = (Path(__file__).parent.parent / 'commands' / f"{command}.py").resolve()
            if not module_path.exists():
                self.soul_handler.logger.error(f'module path not exists, {module_path}')
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
                        self.logger.info(f"Loaded command module: {command}")
                    else:
                        self.logger.error(f"Failed to load command module: {command}")
                except Exception as e:
                    self.logger.error(f"Error loading command {command}: {traceback.format_exc()}")
                
        except Exception as e:
            self.logger.error(f"Error loading commands: {traceback.format_exc()}")

    async def start_monitoring(self):
        enabled = True
        response = None
        lyrics = None
        last_info = None
        error_count = 0
        
        # Load all command modules
        self._load_all_commands()
        self.logger.info("All command modules loaded")
        
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
                messages = await self.soul_handler.get_latest_message(enabled)
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
                                if cmd == 'enable':
                                    enabled = ''.join(command_info['parameters']) == "1"
                                    self.soul_handler.logger.info(f"start_monitoring enabled: {enabled}")
                                    response = command_info['response_template'].format(
                                        enabled=enabled
                                    )
                                    self.soul_handler.send_message(response)

                                if not enabled:
                                    continue

                                self.soul_handler.send_message(
                                    f'Processing :{cmd} command @{message_info.nickname}')

                                match command_info['prefix']:
                                    case 'invite':
                                        # Get party ID parameter
                                        if len(command_info['parameters']) > 0:
                                            party_id = command_info['parameters'][0]
                                            # Try to join party
                                            result = self.soul_handler.invite_user(message_info, party_id)

                                            if 'error' in result:
                                                # Use error template if invitation failed
                                                response = command_info['error_template'].format(
                                                    party_id=result['party_id'],
                                                    error=result['error']
                                                )
                                            else:
                                                # Use success template if invitation succeeded
                                                response = command_info['response_template'].format(
                                                    party_id=result['party_id'],
                                                    user=message_info.nickname
                                                )
                                        else:
                                            response = command_info['error_template'].format(
                                                party_id='unknown',
                                                error='Missing party ID parameter'
                                            )
                                    case _:
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
                self.connection_error_count = 0  # Reset connection error count on success
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
                self.soul_handler.log_error(f'[start_monitoring]WebDriverException, traceback: {traceback.format_exc()}')
                
                # Check if it's a connection error
                if self._is_connection_error(e):
                    if self._handle_connection_error(e):
                        continue  # Retry the loop
                    else:
                        self.is_running = False
                        return False
                else:
                    # Regular WebDriverException, use existing logic
                    error_count += 1
                    if error_count > 9:
                        self.is_running = False
                        return False
        return None
