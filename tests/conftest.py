import pytest

from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.command_manager import CommandManager
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.managers.timer_manager import TimerManager


@pytest.fixture(autouse=True)
def initialized_test_singletons():
    """Provide dependency-free singleton services and isolate every test."""
    Singleton.reset_all_instances()
    for singleton_class in (
        MessageQueue,
        MessageDispatch,
        CommandManager,
        EventManager,
        PartyManager,
        TimerManager,
    ):
        singleton_class.initialize()

    yield

    Singleton.reset_all_instances()
