"""在线校验适配器：关键字添加只允许在线用户。"""

from ushareiplay.modules.command.ports import UserPresence


class InfoManagerPresence(UserPresence):
    def __init__(self, info_manager):
        self._info_manager = info_manager

    def is_user_online(self, username: str) -> bool:
        return self._info_manager.is_user_online(username)
