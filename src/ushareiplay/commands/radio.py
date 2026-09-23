"""Radio command -- thin adapter into the Radio Workflow module.

All radio selection, navigation, metadata parsing, old-song policy, room
context updates, and return-to-Soul behavior live in
``ushareiplay.core.radio_workflow.RadioWorkflow``. This module only adapts
the command seam to that workflow.
"""

from typing import Optional
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.core.radio_workflow import RadioWorkflow
from ushareiplay.helpers.song_release import QQMusicSongReleaseLookup


class RadioCommand(BaseCommand):
    playback_muting = True

    def __init__(self, controller):
        super().__init__(controller)
        self.song_release_lookup = QQMusicSongReleaseLookup()
        self._workflow = None

    @property
    def workflow(self):
        if self._workflow is None:
            title_mgr = None
            try:
                title_mgr = self.title_manager
            except Exception:
                pass
            topic_mgr = None
            try:
                topic_mgr = self.topic_manager
            except Exception:
                pass
            self._workflow = RadioWorkflow(
                music_ui=self.music_handler,
                soul_ui=self.soul_handler,
                info_manager=self.info_manager,
                title_manager=title_mgr,
                topic_manager=topic_mgr,
                song_release_lookup=self.song_release_lookup,
                config=getattr(self.controller, "config", None) or {},
            )
        return self._workflow

    async def do_process(self, message_info, parameters):
        # 歌单守护检查：若当前播放者不是管理员且仍在房间（含分身），阻断切歌
        config = getattr(self.controller, "config", None)
        protection_error = await self.info_manager.check_playlist_protection(
            message_info.nickname, config=config
        )
        if protection_error:
            self.music_handler.logger.info(
                f"{message_info.nickname} 尝试播放电台，但 {self.info_manager.player_name} 正在播放"
            )
            return protection_error

        if not parameters:
            return self._handle_collection(message_info)

        return self.workflow.dispatch(message_info, parameters)

    def _handle_collection(self, message_info):
        return self.workflow._handle_collection(message_info)

    def _handle_guess_like(self, message_info):
        return self.workflow._handle_guess_like(message_info)

    def _handle_daily_30(self, message_info):
        return self.workflow._handle_daily_30(message_info)

    def _handle_sleep_healing(self, message_info):
        return self.workflow._handle_sleep_healing(message_info)

    def _handle_radar(self, message_info):
        return self.workflow._handle_radar(message_info)
