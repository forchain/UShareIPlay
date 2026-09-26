import shlex
import traceback

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.dal.focus_event_dao import FocusEventDao


class FocusCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理专注人数命令时出错'

    async def do_process(self, message_info, parameters):
        try:
            original_content = message_info.content
            parts = original_content.split(None, 1)
            if len(parts) < 2:
                return {"error": "缺少参数。使用: :focus [add|del|list|clear]"}

            params = shlex.split(parts[1])
        except ValueError:
            return {"error": "参数格式错误，带空格的参数请使用引号包裹"}

        if not params:
            return {"error": "缺少参数。使用: :focus [add|del|list|clear]"}

        operation = params[0]
        username = message_info.nickname

        if operation == "add":
            if len(params) < 2:
                return {"error": '缺少命令内容。使用: :focus add "命令内容"'}

            command = params[1]
            if not command.startswith((":", "：", "/", "／")):
                return {"error": '命令必须以命令前缀(:/：或//／)开头，例如 ":play 歌曲名"'}

            await FocusEventDao.create(username, command)
            return {"message": f"已添加专注人数联动命令: {command}"}

        if operation == "del":
            if len(params) < 2:
                return {"error": "缺少命令ID。使用: :focus del <id>"}
            try:
                command_id = int(params[1])
            except ValueError:
                return {"error": "命令ID必须是数字"}

            deleted = await FocusEventDao.delete_by_id(command_id)
            if deleted:
                return {"message": f"已删除命令 ID: {command_id}"}
            return {"error": f"未找到命令 ID: {command_id}"}

        if operation == "list":
            commands = await FocusEventDao.get_by_username(username)
            if not commands:
                return {"message": "您还没有设置任何专注人数联动命令"}

            lines = ["您的专注人数联动命令列表:"]
            for cmd in commands:
                lines.append(f"  [{cmd.id}] {cmd.command}")
            return {"message": "\n".join(lines)}

        if operation == "clear":
            count = await FocusEventDao.delete_all_by_username(username)
            if count > 0:
                return {"message": f"已清除 {count} 个专注人数联动命令"}
            return {"message": "您没有任何专注人数联动命令需要清除"}

        return {"error": f"未知操作: {operation}。使用: :focus [add|del|list|clear]"}

    async def focus_count_change(
        self,
        before: int | None,
        after: int,
        changed_users: list[str] | None = None,
        seat_info: dict | None = None,
    ):
        """专注人数变化或特定用户麦位变动时执行。

        若指定了 changed_users，仅检索并入队这部分用户的 :focus add 配置（用户级隔离）；
        若未指定 changed_users（兼容旧调用），则回退为执行所有用户的联动命令。
        """
        try:
            from ushareiplay.core.message_queue import MessageQueue
            from ushareiplay.models.message_info import MessageInfo

            commands = []
            if changed_users is not None:
                for username in changed_users:
                    user_cmds = await FocusEventDao.get_by_username(username)
                    commands.extend(user_cmds)
            else:
                commands = await FocusEventDao.get_all_ordered()

            if not commands:
                return

            self.handler.logger.info(
                f"Focus change {before} -> {after}, queuing {len(commands)} focus command(s) "
                f"for changed users: {changed_users if changed_users is not None else 'all'}"
            )

            message_queue = MessageQueue.instance()
            seat_info = seat_info or {}
            for cmd in commands:
                username = cmd.user.username
                cmd_text = cmd.command
                user_seat = seat_info.get(username, {})
                seat_num = str(user_seat.get("seat_number", ""))
                action = str(user_seat.get("action", ""))
                cmd_text = (
                    cmd_text.replace("{username}", username)
                    .replace("{seat}", seat_num)
                    .replace("{action}", action)
                )

                message_info = MessageInfo(content=cmd_text, nickname=username)
                await message_queue.put_message(message_info)
                self.handler.logger.info(
                    f"Queued focus event command [{cmd.id}] for {username}: {cmd_text}"
                )
        except Exception:
            self.handler.log_error(f"Error in focus_count_change: {traceback.format_exc()}")
