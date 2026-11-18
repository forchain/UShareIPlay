"""
验证重构后所有子包的 import 路径正确，无 ModuleNotFoundError。
"""
import importlib
import pytest


MODULES = [
    # core
    "ushareiplay.core.singleton",
    "ushareiplay.core.config_loader",
    "ushareiplay.adapters.outbound.persistence.db_manager",
    "ushareiplay.core.message_queue",
    "ushareiplay.core.post_party_create_automation",
    "ushareiplay.core.runtime_services",
    "ushareiplay.core.runtime_context",
    "ushareiplay.core.command_parser",
    "ushareiplay.core.log_formatter",
    "ushareiplay.core.element_wrapper",
    "ushareiplay.core.driver_decorator",
    "ushareiplay.core.ui",
    "ushareiplay.core.ui.element_finder",
    "ushareiplay.core.ui.gesture_handler",
    "ushareiplay.core.ui.key_actions",
    "ushareiplay.core.ui.navigation",
    # models
    "ushareiplay.models",
    "ushareiplay.adapters.outbound.persistence",
    "ushareiplay.adapters.outbound.persistence.models",
    "ushareiplay.adapters.outbound.persistence.models.user",
    "ushareiplay.adapters.outbound.persistence.models.seat_reservation",
    "ushareiplay.adapters.outbound.persistence.models.keyword",
    "ushareiplay.models.message_info",
    "ushareiplay.modules.timer.domain",
    "ushareiplay.modules.room.domain",
    "ushareiplay.modules.room.ports",
    "ushareiplay.modules.room.registry",
    "ushareiplay.modules.room.use_cases",
    "ushareiplay.adapters.outbound.persistence.room_state_store",
    "ushareiplay.adapters.outbound.persistence.user_event_hook_repository",
    "ushareiplay.adapters.outbound.appium.soul.online_list_source",
    "ushareiplay.adapters.inbound.runtime.hook_command_sink",
    "ushareiplay.adapters.inbound.chat.enter",
    "ushareiplay.adapters.inbound.chat.exit",
    "ushareiplay.adapters.inbound.chat.focus",
    "ushareiplay.adapters.inbound.chat.return",
    "ushareiplay.adapters.inbound.chat.receive",
    "ushareiplay.modules.timer.ports",
    "ushareiplay.modules.timer.use_cases",
    "ushareiplay.modules.mic.domain",
    "ushareiplay.modules.mic.ports",
    "ushareiplay.modules.mic.use_cases",
    "ushareiplay.adapters.outbound.appium.soul.mic_control",
    "ushareiplay.adapters.inbound.chat.mic",
    "ushareiplay.adapters.outbound.persistence.timer_repository",
    "ushareiplay.adapters.inbound.runtime.timer_message_sink",
    "ushareiplay.adapters.inbound.chat.timer",
    "ushareiplay.adapters.outbound.persistence.models.enter_event",
    "ushareiplay.adapters.outbound.persistence.models.exit_event",
    "ushareiplay.adapters.outbound.persistence.models.return_event",
    "ushareiplay.adapters.outbound.persistence.models.timer",
    "ushareiplay.adapters.outbound.persistence.models.user_chat_log",
    "ushareiplay.adapters.outbound.persistence.models.user_memory",
    # dal
    "ushareiplay.dal",
    "ushareiplay.dal.user_dao",
    "ushareiplay.adapters.outbound.persistence.seat_reservation_repository",
    "ushareiplay.modules.seat.domain",
    "ushareiplay.modules.seat.ledger",
    "ushareiplay.modules.seat.macros",
    "ushareiplay.modules.seat.ports",
    "ushareiplay.modules.seat.use_cases",
    "ushareiplay.adapters.outbound.llm.memory_distiller",
    "ushareiplay.adapters.outbound.persistence.chat_log_repository",
    "ushareiplay.adapters.outbound.persistence.user_memory_repository",
    # helpers

    "ushareiplay.helpers.playlist_parser",
    # playback (#554)
    "ushareiplay.modules.playback",
    "ushareiplay.modules.playback.domain",
    "ushareiplay.modules.playback.ports",
    "ushareiplay.modules.playback.use_cases",
    "ushareiplay.adapters.inbound.chat.play",
    "ushareiplay.adapters.inbound.chat.fav",
    "ushareiplay.adapters.inbound.chat.skip",
    "ushareiplay.adapters.inbound.chat.next",
    "ushareiplay.adapters.inbound.chat.singer",
    "ushareiplay.adapters.inbound.chat.album",
    "ushareiplay.adapters.inbound.chat.playlist",
    "ushareiplay.adapters.inbound.chat.radio",
    "ushareiplay.adapters.inbound.chat.pause",
    "ushareiplay.adapters.inbound.chat.vol",
    "ushareiplay.adapters.inbound.chat.lyrics",
    "ushareiplay.adapters.inbound.chat.mode",
    "ushareiplay.adapters.inbound.chat.acc",
    "ushareiplay.adapters.outbound.appium.qq_music",
    "ushareiplay.adapters.outbound.appium.qq_music.qq_music_handler",
    "ushareiplay.adapters.outbound.appium.qq_music.qq_music_ui_driver",
    "ushareiplay.adapters.outbound.appium.qq_music.player_page",
    "ushareiplay.adapters.outbound.appium.qq_music.media_session",
    # 房间档案
    "ushareiplay.modules.room.room_profile",
    "ushareiplay.modules.room.row_editor",
    "ushareiplay.adapters.outbound.appium.soul.room_profile",
]


@pytest.mark.parametrize("module_path", MODULES)
def test_module_importable(module_path):
    """每个模块都应该可以 import，不抛 ModuleNotFoundError 或 ImportError。"""
    mod = importlib.import_module(module_path)
    assert mod is not None
