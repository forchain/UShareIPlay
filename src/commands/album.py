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

        play_all = self.handler.wait_for_element_clickable_plus('play_all')
        if not play_all:
            self.handler.logger.error(f"Failed to find play all with query {query}")
            return {'error': 'Failed to find play all button'}
        play_all.click()
        self.handler.logger.info("play all clicked")

        self.controller.topic_command.change_topic(topic)
        self.handler.logger.info(f"change album topic to {topic}")

        return {
            'album': topic
        }
