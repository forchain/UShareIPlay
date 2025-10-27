import time
import traceback
from datetime import datetime

from ..core.base_command import BaseCommand


def create_command(controller):
    topic_command = TopicCommand(controller)
    controller.topic_command = topic_command
    return topic_command


command = None


class TopicCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)

        self.last_update_time = None
        self.current_topic = None
        self.next_topic = None
        self.cooldown_minutes = 5
        self.handler = self.soul_handler

    def change_topic(self, topic: str):

        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.handler.logger.info("Switched to Soul app")

        new_topic = topic.split('|')[0].split('(')[0].strip()[:15]
        current_time = datetime.now()

        # Update topic
        self.next_topic = new_topic

        if not self.last_update_time:
            self.handler.logger.info(f'Topic will be updated to {new_topic} soon')
            return {
                'topic': f'{new_topic}. Topic will update soon'
            }

        time_diff = current_time - self.last_update_time
        remaining_minutes = self.cooldown_minutes - (time_diff.total_seconds() / 60)
        if remaining_minutes < 0:
            self.handler.logger.info(f'Topic will be updated to {new_topic} soon')
            return {
                'topic': f'{new_topic}. Topic will update soon'
            }

        self.handler.logger.info(f'Topic will be updated to {new_topic} in {remaining_minutes} minutes')
        return {
            'topic': f'{new_topic}. Topic will update in {int(remaining_minutes)} minutes'
        }

    async def process(self, message_info, parameters):
        """Process topic command"""
        try:
            # Get new topic from parameters
            if not parameters:
                return {'error': 'Missing topic parameter'}

            new_topic = ' '.join(parameters)
            return self.change_topic(new_topic)
        except Exception as e:
            self.handler.log_error(f"Error processing topic command: {str(e)}")
            return {'error': f'Failed to process topic command, {new_topic}'}

    def update(self):
        """Check and update topic periodically"""

        try:
            if not self.next_topic:
                return

            on_time = False
            current_time = datetime.now()
            if self.last_update_time:
                time_diff = current_time - self.last_update_time
                if time_diff.total_seconds() >= self.cooldown_minutes * 60:
                    on_time = True
            else:
                on_time = True

            if not on_time:
                return

            # Update cooldown time BEFORE attempting operation
            self.last_update_time = current_time
            self.handler.logger.info(
                f'Updated last topic update time to {current_time}, next topic: {self.next_topic}')

            # Use TopicManager to update topic
            from ..managers.topic_manager import TopicManager
            topic_manager = TopicManager.instance()

            result = topic_manager.change_topic(self.next_topic)

            # Update local state if successful
            if 'error' not in result:
                if self.next_topic:
                    self.current_topic = self.next_topic
                    self.next_topic = None
                    self.handler.logger.info(f'Updated current topic to {self.current_topic}')
                else:
                    self.handler.logger.warning(f'Next topic is empty, current topic: {self.current_topic}')

                self.handler.logger.info(f'Topic is updated to {self.current_topic}')
                self.handler.send_message(
                    f"Updating topic to {self.current_topic}"
                )
            else:
                self.handler.logger.warning(f'Failed to update topic: {result.get("error")}')

        except Exception as e:
            self.handler.log_error(f"Error in topic update: {traceback.format_exc()}")
