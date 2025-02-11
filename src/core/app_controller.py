from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common import WebDriverException, StaleElementReferenceException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.common import AppiumOptions
from ..soul.soul_handler import SoulHandler
from ..music.qq_music_handler import QQMusicHandler
from ..utils.command_parser import CommandParser
from ..utils.lyrics_formatter import LyricsFormatter
import time
import traceback
import importlib
import os
from pathlib import Path
import sys
import threading
import queue
import readline  # 用于更好的命令行输入体验


class AppController:
    def __init__(self, config):
        self.config = config
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

        # Create lyrics formatter
        self.lyrics_formatter = LyricsFormatter(lyrics_tags)

        # Initialize handlers
        self.soul_handler = SoulHandler(self.driver, config['soul'], self)
        self.music_handler = QQMusicHandler(self.driver, config['qq_music'], self)
        self.music_handler.set_lyrics_formatter(self.lyrics_formatter)
        self.logger = self.soul_handler.logger

        # Initialize command parser
        self.command_parser = CommandParser(config['commands'])

        self.commands_path = Path(__file__).parent.parent / 'commands'
        self.command_modules = {}  # Cache for loaded command modules

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
            self.soul_handler.log_error(f"Error loading command module {command}: {str(e)}")
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

    def _process_command(self, command, message_info, command_info):
        """Process command using module if available
        Args:
            message_info: MessageInfo object
            command_info: dict containing command details
        Returns:
            str: Response message
        """
        try:
            # self.soul_handler.send_message(f"Processing command :{command_info['prefix']}\n@{message_info.nickname}")
            result = command.process(message_info, command_info['parameters'])
            if 'error' in result:
                res =  command_info['error_template'].format(
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
                if user_input.strip():  # 只处理非空输入
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

    def start_monitoring(self):
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
                # Check for console input
                try:
                    while not self.input_queue.empty():
                        message = self.input_queue.get_nowait()
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
                    if not 'album' in info or info['album'] == info['singer'] :
                        self.music_handler.skip_song()
                    elif info['song'].endswith('(Live)'):
                        if self.music_handler.live_count > 0:
                            self.music_handler.live_count -= 1
                        else:
                            self.music_handler.skip_song()
                    elif 'DJ' in info['song'] or 'Remix' in info['song']:
                        self.music_handler.skip_song()
                    else:
                        self.soul_handler.send_message(f"Playing {info['song']} by {info['singer']} in {info['album']}")

                # Monitor Soul messages
                messages = self.soul_handler.get_latest_message(enabled)
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
                                            response = self._process_command(command, message_info, command_info)
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
