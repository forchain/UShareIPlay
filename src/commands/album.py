import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time


def create_command(controller):
    album_command = AlbumCommand(controller)
    controller.album_command = album_command
    return album_command


command = None


class AlbumCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    def process(self, message_info, parameters):
        query = ' '.join(parameters)
        self.soul_handler.ensure_mic_active()
        self.controller.player_name = message_info.nickname
        info = self.play_album(query)
        return info

    def select_album_tab(self):

        tab = self.handler.wait_for_element_clickable_plus('album_tab')
        if not tab:
            self.handler.logger.error("Cannot find album tab")
            return False

        tab.click()
        self.handler.logger.info("Selected album tab")
        return True

    def play_album(self, query):
        if query == "":
            info = self.handler.get_playback_info()
            if not info:
                self.handler.logger.error(f"Failed to get playback info with query {query}")
                return {'error': f'Failed to get playback info'}
            query = f'{info["song"]} {info["singer"]} {info["album"]}'
        if not self.handler.query_music(query):
            self.handler.logger.error(f"Failed to query music with query {query}")
            return {
                'error': 'Failed to query album',
            }
        if not self.select_album_tab():
            self.handler.logger.error(f"Failed to select lyrics tab with query {query}")
            return {
                'error': 'Failed to select lyrics tab',
            }

        album_text = self.handler.wait_for_element_clickable_plus('album_text')
        if not album_text:
            self.handler.logger.error(f"Failed to find album text with query {query}")
            return {'error': 'Failed to find album text'}
        topic = album_text.text
        album_singer = self.handler.try_find_element_plus('album_singer')
        if album_singer:
            with_singer = f'{topic} {album_singer.text.split(' ')[0]}'
            topic = with_singer if len(with_singer) <= 15 else topic

        album_text.click()
        self.handler.logger.info("album text clicked")

        singer_container = self.handler.wait_for_element_plus('singer_container')
        if not singer_container:
            self.handler.logger.error(f"Failed to find singer container with query {query}")
            return {'error': 'Failed to find singer container'}

        play_all = self.handler.try_find_element_plus('play_all')
        play_all_mini = self.handler.try_find_element_plus('play_all_mini')

        if play_all_mini :
            play_button = play_all_mini
            self.handler.logger.info("play all mini button found")
        elif play_all:
            play_button = play_all
            self.handler.logger.info("play all button found")
        else:
            self.handler.logger.error(f"Failed to find play button for query {query}")
            return {'error': 'Failed to find play button'}

        play_button.click()
        self.handler.logger.info("play button clicked")

        self.controller.topic_command.change_topic(topic)
        self.handler.logger.info(f"changing album topic to {topic}")
        self.controller.title_command.change_title(topic)
        self.handler.logger.info(f"changing album title  to {topic}")

        return {
            'album': topic
        }
