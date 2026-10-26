def _extract_level(subcommand_config):
    """从子命令配置里取出等级，兼容字典（{'level': 1}）与标量简写（1）。"""
    if isinstance(subcommand_config, dict):
        level = subcommand_config.get('level')
        return int(level) if level is not None else None
    if isinstance(subcommand_config, (int, float)):
        return int(subcommand_config)
    if isinstance(subcommand_config, str) and subcommand_config.strip():
        return int(subcommand_config)
    return None


def resolve_command_level(command_info, parameters):
    """解析一次命令调用所需的权限等级。

    匹配顺序：
      1. 无参调用 -> `subcommands['']`
      2. 首参数（忽略大小写）命中具名子命令 -> `subcommands[<name>]`
      3. 其余带参调用 -> `subcommands['*']`
      4. 都没命中 -> 顶层 `level`（默认 1）
    """
    subcommands = command_info.get('subcommands')
    if isinstance(subcommands, dict):
        lowered = {str(name).lower(): cfg for name, cfg in subcommands.items()}
        if not parameters:
            key = ''
        else:
            key = str(parameters[0]).lower()
            if key not in lowered:
                key = '*'
        level = _extract_level(lowered.get(key))
        if level is not None:
            return level

    return int(command_info.get('level', 1))


class CommandParser:
    def __init__(self, commands, lyrics_tags=None):
        self.commands = commands
        self.lyrics_tags = lyrics_tags

    def is_valid_command(self, message):
        """Check if message starts with any valid prefix"""
        if not message:
            return False
        msg = message.lstrip().lower()
        return any(msg.startswith(str(cmd.get('prefix', '')).lower()) for cmd in self.commands)

    def parse_command(self, message):
        """Parse command and get the music query"""
        if not message:
            return None
        message = message.lstrip()

        # Split message into command and parameters
        parts = message.split()
        if not parts:
            return None

        command = parts[0].lower()
        parameters = parts[1:]  # All elements after the command

        # Find matching command config
        matching_cmd = None
        for cmd in self.commands:
            if command == str(cmd.get('prefix', '')).lower():
                matching_cmd = cmd
                break

        if not matching_cmd:
            return None

        # Do not mutate shared command configuration; return a per-message copy.
        return {**matching_cmd, "parameters": parameters}