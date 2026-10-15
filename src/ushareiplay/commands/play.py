from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.music_manager import MusicManager
from ushareiplay.managers.playback.models import PlaybackRequest


class PlayCommand(BaseCommand):
    playback_muting = True
    handler_attr = 'music_handler'

    def playback_expected_song(self, parameters):
        query = ' '.join(parameters or [])
        if not query or query == '?':
            return None
        return query

    def playback_muting_applies(self, parameters):
        """点歌分支不参与命令级静音：麦克风生命周期归 `MusicManager.play()`。

        命令级守卫在守护之前就闭麦，于是「小红正在播放歌单，请等待」这句回复
        之前已经闭过一次麦 —— 房间里只听见一段没有来由的静音。迁移到引擎后，
        守护通过才会闭麦。

        收藏与电台分支尚未迁移（#425），仍靠命令级静音保护切歌，因此按分支判定
        而不是一刀切地关掉整个命令的静音参与。
        """
        query = ' '.join(parameters or [])
        return query in ('', '?')

    async def do_process(self, message_info, parameters):
        query = ' '.join(parameters)

        if query == '':
            playing_info = self.play_favorites(message_info.nickname)
            return playing_info
        elif query == '?':
            playing_info = self.play_radar(message_info.nickname)
            return playing_info
        else:
            playing_info = await self.play_song(query, message_info.nickname)
            return playing_info

    async def play_song(self, music_query, requester=None):
        """`:play <歌名> [歌手]` —— 单曲点播。

        查歌、点结果、收藏、质量过滤都由 `QQMusicUIDriver` 在引擎的静音守护内
        完成；命令层只负责把请求翻译成 `PlaybackRequest`，再把结果交给公屏模板。
        """
        result = await MusicManager.instance().play(
            PlaybackRequest.song(music_query, requester=requester)
        )
        return result.as_response()

    def play_favorites(self, requester=None):
        """Navigate to favorites and play all"""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        err = self.handler.open_favorites_entry()
        if err:
            return err

        result_item = self.handler.element_finder.try_find_element('result_item')
        song_text = None
        singer_text = None
        if result_item:
            elements = result_item.find_elements(AppiumBy.CLASS_NAME, 'android.widget.TextView')
            if len(elements) >= 3:
                song_text = elements[1].text
                singer_text = elements[2].text

        play_fav = self.handler.element_finder.wait_for_element_clickable('play_all')
        if not play_fav:
            return {'error': 'Cannot find play all button'}
        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        self.playlist_adoption.adopt(
            requester=requester,
            mode='favorites',
            title="O Station",
            topic=song_text,
        )

        return {'song': song_text, 'singer': singer_text, 'album': ''}

    def play_radar(self, requester=None):
        """Navigate to favorites and play all"""
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")
        radar_nav = self.handler.element_finder.try_find_element('radar_nav', log=False)
        if not radar_nav:
            return {'error': 'Cannot find radar_nav'}

        radar_nav.click()
        self.handler.logger.info("Clicked radar navigation button")

        # Click on play all button
        song = self.handler.element_finder.wait_for_element_clickable('radar_song')
        song_text = song.text if song else "Unknown"
        singer = self.handler.element_finder.wait_for_element_clickable('radar_singer')
        singer_text = singer.text if singer else "Unknown"

        self.playlist_adoption.adopt(
            requester=requester,
            mode='radar',
            title="O Radio",
            topic=song_text,
        )

        return {'song': song_text, 'singer': singer_text, 'album': ''}
