"""Radio command -- thin adapter into the Radio Workflow module.

All radio selection, navigation, metadata parsing, old-song policy, room
context updates, and return-to-Soul behavior live in
``ushareiplay.core.radio_workflow.RadioWorkflow``. This module only adapts
the command seam to that workflow.
"""

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.core.radio_workflow import RadioWorkflow
from ushareiplay.helpers.song_release import QQMusicSongReleaseLookup


class RadioCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.song_release_lookup = QQMusicSongReleaseLookup()
        self.workflow = RadioWorkflow(
            music_ui=self.music_handler,
            soul_ui=self.soul_handler,
            info_manager=self.info_manager,
            title_manager=self.title_manager,
            topic_manager=self.topic_manager,
            song_release_lookup=self.song_release_lookup,
            config=self.controller.config or {},
        )

    async def do_process(self, message_info, parameters):
        return self.workflow.dispatch(message_info, parameters)
