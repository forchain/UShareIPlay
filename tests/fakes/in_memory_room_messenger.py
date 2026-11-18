"""`RoomMessenger` 的内存替身：记录送达与静音抑制的公屏消息。"""

from ushareiplay.modules.shared.ports import RoomMessenger


class InMemoryRoomMessenger(RoomMessenger):
    def __init__(self):
        self.messages: list[str] = []
        self.suppressed: list[str] = []

    def send_screen_message(self, message: str, silent: bool = False):
        if silent:
            self.suppressed.append(message)
            return None
        self.messages.append(message)
        return None
