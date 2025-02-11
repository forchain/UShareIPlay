import traceback

from trio import current_time

from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time


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
        self.cooldown_minutes = 5 + 2
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

    def process(self, message_info, parameters):
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
        # super().update()

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

            result = self._update_topic(self.next_topic)
            if not 'error' in result:
                self.handler.logger.info(f'Topic is updated to {self.current_topic}')
                self.handler.send_message(
                    f"Updating topic to {self.current_topic}"
                )

        except Exception as e:
            self.handler.log_error(f"Error in topic update: {traceback.format_exc()}")

    def _update_topic(self, topic):
        """Update room topic
        Args:
            topic: New topic text
        Returns:
            dict: Result with error or success
        """
        try:
            # Click room topic
            room_topic = self.handler.wait_for_element_clickable_plus('room_topic')
            if not room_topic:
                return {'error': 'Failed to find room topic'}
            room_topic.click()

            # Click edit entry
            edit_entry = self.handler.wait_for_element_clickable_plus('edit_topic_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit topic entry'}
            edit_entry.click()

            # Input new topic
            topic_input = self.handler.wait_for_element_clickable_plus('edit_topic_input')
            if not topic_input:
                return {'error': 'Failed to find topic input'}
            topic_input.clear()
            topic_input.send_keys(topic)

            # Click confirm
            confirm = self.handler.wait_for_element_clickable_plus('edit_topic_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()

            # note: update status in advance in case failing to find the edit entry
            current_time = datetime.now()
            self.last_update_time = current_time
            self.handler.logger.info(f'updated last topic update time to {current_time}')
            self.current_topic = self.next_topic
            self.next_topic = None

            self.handler.press_back()
            self.handler.logger.info('Hide edit topic dialog')

            return {'success': True}

        except Exception as e:
            self.handler.log_error(f"Error in topic update: {traceback.format_exc()}")
            return {'error': f'Failed to update topic: {topic}'}
