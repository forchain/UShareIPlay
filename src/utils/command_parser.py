class CommandParser:
    def __init__(self, config):
        self.prefix = config['prefix']

    def is_valid_command(self, message):
        """检查是否是有效的命令"""
        if not message:
            return False
        return message.startswith(self.prefix)

    def parse_command(self, message):
        """解析命令获取歌名和歌手"""
        # 移除前缀
        content = message[len(self.prefix):].strip()
        # 分割歌名和歌手
        parts = content.split()
        if len(parts) >= 2:
            song = parts[0]
            singer = parts[1]
            return song, singer
        return None, None 