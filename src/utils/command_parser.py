class CommandParser:
    def __init__(self, config):
        self.prefix = config['prefix']

    def is_valid_command(self, message):
        """检查是否是有效的命令"""
        if not message:
            return False
        return message.startswith(self.prefix)

    def parse_command(self, message):
        """解析命令获取音乐搜索关键词"""
        # 移除前缀
        content = message[len(self.prefix):].strip()
        if content:
            return content
        return None 