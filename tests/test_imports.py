"""
验证重构后所有子包的 import 路径正确，无 ModuleNotFoundError。
"""
import importlib
import pytest


MODULES = [
    # core
    "ushareiplay.core.singleton",
    "ushareiplay.core.config_loader",
    "ushareiplay.core.db_manager",
    "ushareiplay.core.db_service",
    "ushareiplay.core.message_queue",
    "ushareiplay.core.command_parser",
    "ushareiplay.core.log_formatter",
    "ushareiplay.core.element_wrapper",
    "ushareiplay.core.driver_decorator",
    # models
    "ushareiplay.models",
    "ushareiplay.models.user",
    "ushareiplay.models.seat_reservation",
    "ushareiplay.models.keyword",
    "ushareiplay.models.message_info",
    "ushareiplay.models.enter_event",
    "ushareiplay.models.exit_event",
    "ushareiplay.models.return_event",
    "ushareiplay.models.timer",
    # dal
    "ushareiplay.dal",
    "ushareiplay.dal.user_dao",
    "ushareiplay.dal.keyword_dao",
    "ushareiplay.dal.seat_reservation_dao",
    "ushareiplay.dal.timer_dao",
    "ushareiplay.dal.enter_dao",
    "ushareiplay.dal.exit_dao",
    "ushareiplay.dal.return_dao",
    # helpers
    "ushareiplay.helpers.playlist_parser",
]


@pytest.mark.parametrize("module_path", MODULES)
def test_module_importable(module_path):
    """每个模块都应该可以 import，不抛 ModuleNotFoundError 或 ImportError。"""
    mod = importlib.import_module(module_path)
    assert mod is not None
