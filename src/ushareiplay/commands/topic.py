from ushareiplay.core.base_command import BaseCommand


class TopicCommand(BaseCommand):
    """话题命令 —— 只解析参数，业务全在 `RoomProfileManager` 里。

    参数拼接、无参数时的状态回复拼装留在命令这一层（它们决定的是聊天气泡里
    长什么样），排队、冷却、写黑板都在房间档案模块内。`handler_attr` 与
    `error_message` 保持原样，因此 config.yaml 里 `:topic` 的响应/错误模板
    不需要改。
    """

    handler_attr = 'soul_handler'
    error_message = 'Failed to process topic command'

    async def do_process(self, message_info, parameters):
        """
        处理话题命令
        - 无参数时返回当前状态
        - 有参数时安排话题变更
        """
        # 无参数时返回状态信息
        if not parameters:
            status = self.room_profile_manager.get_topic_status()

            current = status['current_topic']
            next_topic = status['next_topic']
            remaining = status['remaining_time']

            message = f"Current topic: {current}\n"
            message += f"Next topic: {next_topic}"

            if remaining is not None:
                if remaining > 0:
                    message += f"\nWill update in {remaining} minute(s)"
                else:
                    message += "\nWill update soon"

            # 返回 topic 键以匹配 response_template
            return {'topic': message}

        # 有参数时安排话题变更
        new_topic = ' '.join(parameters)
        return self.room_profile_manager.set_topic(new_topic)

    def update(self):
        """心跳：冷却到期的话题由 `RoomProfileManager` 写进黑板。

        返回值一律忽略 —— 这里没有需要回给用户的东西，日志由房间档案模块按
        「有行为才打」的原则自己负责。
        """
        self.room_profile_manager.update_topic()
