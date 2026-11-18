"""用户聊天日志记录适配器：供关键字链路把 @ 群主发言交给记忆系统。"""

from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
from ushareiplay.modules.command.ports import ChatLogRecorder


class TortoiseChatLogRecorder(ChatLogRecorder):
    async def record(self, username: str, content: str) -> None:
        await UserChatLogDAO.create(username=username, content=content)
