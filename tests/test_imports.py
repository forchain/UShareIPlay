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
    "ushareiplay.modules.room.macros",
    "ushareiplay.modules.room.use_cases",
    "ushareiplay.adapters.outbound.persistence.room_state_store",
    "ushareiplay.adapters.outbound.persistence.user_event_hook_repository",
    "ushareiplay.adapters.outbound.appium.soul.online_list_source",
    "ushareiplay.adapters.inbound.runtime.hook_command_sink",
    "ushareiplay.adapters.inbound.chat.enter",
    "ushareiplay.adapters.inbound.chat.exit",
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
    "ushareiplay.dal.seat_reservation_dao",
    "ushareiplay.adapters.outbound.llm.memory_distiller",
    "ushareiplay.adapters.outbound.persistence.chat_log_repository",
    "ushareiplay.adapters.outbound.persistence.user_memory_repository",
    # helpers

    "ushareiplay.helpers.playlist_parser",
    # managers (深度播放引擎，#379 新增子包)
    "ushareiplay.managers.playback",
    "ushareiplay.managers.playback.models",
    "ushareiplay.managers.playback.driver",
    "ushareiplay.managers.playback.qq_music_ui_driver",
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
