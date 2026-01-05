import importlib
import sys
import traceback
from pathlib import Path
from ..core.singleton import Singleton
from ..core.command_parser import CommandParser


class CommandManager(Singleton):
    """
    命令管理器 - 管理所有命令相关的逻辑
    单例模式，提供统一的命令管理服务
    """

    def __init__(self):
        # 延迟初始化 handler 和 logger，避免循环依赖
        self._handler = None
        self._logger = None

        # 命令相关属性
        self.commands_path = Path(__file__).parent.parent / 'commands'
        self.command_modules = {}  # Cache for loaded command modules
        self.command_parser = None  # Will be initialized when needed

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    def initialize_parser(self, commands_config):
        """
        初始化命令解析器
        Args:
            commands_config: 命令配置列表
        """
        self.command_parser = CommandParser(commands_config)
        self.logger.info("Command parser initialized")

    def load_command_module(self, command):
        """Load command module dynamically"""
        try:
            if command in self.command_modules:
                return self.command_modules[command]

            module_path = (Path(__file__).parent.parent / 'commands' / f"{command}.py").resolve()
            if not module_path.exists():
                self.logger.error(f'module path not exists, {module_path}')
                return None

            package_name = f"src.commands.{command}"
            spec = importlib.util.spec_from_file_location(package_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)

            if not module:
                self.logger.error('Command module failed to load')
                return None

            if not hasattr(module, 'command'):
                self.logger.error('Command module does not have command')
                return None

            # Create command instance
            if not hasattr(module, 'create_command'):
                self.logger.error('Command module does not have create_command')
                return None

            # 获取 AppController 单例实例
            from ..core.app_controller import AppController
            controller = AppController.instance()

            module.command = module.create_command(controller)
            self.command_modules[command] = module
            return module

        except Exception:
            self.logger.error(f"Error loading command module {command}: {traceback.format_exc()}")
            return None

    def load_all_commands(self):
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
                    module = self.load_command_module(command)
                    if module:
                        self.logger.info(f"Loaded command module: {command}")
                    else:
                        self.logger.error(f"Failed to load command module: {command}")
                except Exception:
                    self.logger.error(f"Error loading command {command}: {traceback.format_exc()}")

        except Exception:
            self.logger.error(f"Error loading commands: {traceback.format_exc()}")

    def update_commands(self):
        """Update all loaded commands"""
        for module in self.command_modules.values():
            try:
                if hasattr(module, 'command'):
                    module.command.update()
            except Exception as e:
                self.logger.error(f"Error updating command {module.__name__}: {str(e)}")

    def get_command(self, command_name):
        """Get command by name"""
        module = self.load_command_module(command_name)
        return module.command if module else None

    async def process_command(self, command, message_info, command_info):
        """Process command using module if available
        Args:
            command: Command instance
            message_info: MessageInfo object
            command_info: dict containing command details
        Returns:
            str: Response message
        """
        try:
            parameters = command_info['parameters']
            # UI 互斥：命令执行期间禁止 EventManager 的“未知页面自动 back”打断弹窗/子页面流程
            # 延迟导入避免循环依赖
            from ..core.app_controller import AppController
            result = {'error': 'unknown'}
            if controller := AppController.instance():
                async with controller.ui_session(f"command:{command_info.get('prefix', 'unknown')}"):
                    result = await command.process(message_info, parameters)

            if 'error' in result:
                res = command_info['error_template'].format(
                    error=result['error'],
                    user=message_info.nickname,
                )
            else:
                res = f'{command_info["response_template"].format(**result)} @{message_info.nickname}'
            return res
        except Exception:
            self.logger.error(f"Error processing command {command_info}: {traceback.format_exc()}")
            return f"Error processing command {command_info}"

    def is_valid_command(self, content):
        """Check if content is a valid command"""
        if not self.command_parser:
            self.logger.error("Command parser not initialized")
            return False
        return self.command_parser.is_valid_command(content)

    def parse_command(self, content):
        """Parse command content"""
        if not self.command_parser:
            self.logger.error("Command parser not initialized")
            return None
        return self.command_parser.parse_command(content)

    def initialize_timer_manager(self, config):
        """Initialize timer manager with initial timers from config"""
        try:
            # Check if timer command is loaded
            timer_module = self.command_modules.get('timer')
            if timer_module and hasattr(timer_module, 'command') and hasattr(timer_module.command, 'timer_manager'):
                timer_manager = timer_module.command.timer_manager

                # Load initial timers from config (force update to ensure config values are used)
                initial_timers = config.get('soul', {}).get('initial_timers', [])
                if initial_timers:
                    # Convert config format to new format
                    converted_timers = []
                    for timer_config in initial_timers:
                        converted_timer = {
                            'id': timer_config.get('id'),
                            'target_time': timer_config.get('time'),
                            'message': timer_config.get('message'),
                            'repeat': timer_config.get('repeat', False),
                            'enabled': timer_config.get('enabled', True)
                        }
                        converted_timers.append(converted_timer)

                    # Store initial timers for later loading when timer manager starts
                    # Timer manager will load existing timers first, then these will be added if needed
                    timer_manager._initial_timers = converted_timers
                    timer_manager._force_update = True  # Always force update for initial timers
                    self.logger.info(f"Prepared {len(initial_timers)} initial timers for loading")
                else:
                    self.logger.info("No initial timers configured")
            else:
                self.logger.warning("Timer command not loaded, skipping timer initialization")

        except Exception:
            self.logger.error(f"Error initializing timer manager: {traceback.format_exc()}")

    async def handle_message_commands(self, messages):
        """
        处理消息中的命令
        Args:
            messages: 消息字典 {msg_id: MessageInfo}
        Returns:
            str: 响应消息（如果有的话）
        """
        success_count = 0

        if messages:
            # Iterate through message info objects
            for msg_id, message_info in messages.items():
                if self.is_valid_command(message_info.content):
                    command_info = self.parse_command(message_info.content)
                    if command_info:
                        # Handle different commands using match-case
                        cmd = command_info['prefix']

                        self.handler.send_message(
                            f'Processing :{cmd} command @{message_info.nickname}')

                        command = self.get_command(cmd)
                        if command:
                            response = await self.process_command(command, message_info, command_info)
                            self.handler.send_message(response)
                            success_count += 1
                        else:
                            self.logger.error(f"Unknown command: {cmd}")

        self.logger.info(f"{success_count}/{len(messages)} commands processed")

        return success_count

    def get_command_modules(self):
        """获取所有已加载的命令模块"""
        return self.command_modules

    async def notify_user_leave(self, username: str):
        """
        Notify all commands when a user leaves
        
        Args:
            username: Username of the user who left
        """
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_leave'):
                    await module.command.user_leave(username)
            except Exception:
                self.logger.error(f"Error in command user_leave: {traceback.format_exc()}")

    async def notify_user_enter(self, username: str):
        """
        Notify all commands when a user enters
        
        Args:
            username: Username of the user who entered
        """
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_enter'):
                    await module.command.user_enter(username)
            except Exception:
                self.logger.error(f"Error in command user_enter: {traceback.format_exc()}")
