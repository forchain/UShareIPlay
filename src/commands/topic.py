import traceback
from ..core.base_command import BaseCommand
from ..managers.topic_manager import TopicManager


def create_command(controller):
    topic_command = TopicCommand(controller)
    controller.topic_command = topic_command
    return topic_command


command = None


class TopicCommand(BaseCommand):
    """
    话题命令 - 负责参数解析和调用 TopicManager
    所有业务逻辑在 TopicManager 中实现
    """
    
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self._topic_manager = None
    
    @property
    def topic_manager(self):
        """延迟获取 TopicManager 实例"""
        if self._topic_manager is None:
            self._topic_manager = TopicManager.instance()
        return self._topic_manager

    async def process(self, message_info, parameters):
        """
        处理话题命令
        - 无参数时返回当前状态
        - 有参数时安排话题变更
        """
        try:
            # 无参数时返回状态信息
            if not parameters:
                status = self.topic_manager.get_status()
                
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
            return self.topic_manager.change_topic(new_topic)
            
        except Exception as e:
            self.handler.log_error(f"Error processing topic command: {traceback.format_exc()}")
            return {'error': 'Failed to process topic command'}

    def update(self):
        """定期调用 TopicManager 的 update 方法"""
        try:
            self.topic_manager.update()
        except Exception as e:
            self.handler.log_error(f"Error in topic update: {traceback.format_exc()}")
