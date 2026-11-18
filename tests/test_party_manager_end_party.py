import pytest
from ushareiplay.adapters.outbound.appium.soul.party_driver import SoulPartyDriver
from ushareiplay.modules.room import PartyService, RoomStateService


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Element:
    def __init__(self, name=""):
        self.name = name
        self.clicked = False

    def click(self):
        self.clicked = True


class _MockHandler:
    def __init__(self, config=None, elements=None):
        self.config = config or {}
        self.logger = _Logger()
        self.elements = elements or {}
        self.sent_messages = []
        self.switched = False

    def send_message(self, msg):
        self.sent_messages.append(msg)

    def switch_to_app(self):
        self.switched = True
        return True

    def try_find_element(self, key, log=True):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key, timeout=10):
        return self.elements.get(key)

    def wait_for_any_element(self, keys, timeout=10):
        for k in keys:
            elem = self.elements.get(k)
            if elem:
                return k, elem
        return None, None

    @property
    def element_finder(self):
        return self

    @property
    def key_actions(self):
        return self


def test_end_party_direct_success():
    exit_btn = _Element("exit_room_btn")
    confirm_btn = _Element("confirm_end")

    handler = _MockHandler(elements={
        "exit_room_btn": exit_btn,
        "confirm_end": confirm_btn
    })
    manager = PartyService(
        driver=SoulPartyDriver(handler),
        room_state=RoomStateService(),
        logger=handler.logger,
    )

    res = manager.end_party()

    assert res == {'success': 'Party ended'}
    assert handler.switched is True
    assert exit_btn.clicked is True
    assert confirm_btn.clicked is True


def test_end_party_fallback_success():
    more_menu_btn = _Element("more_menu")
    end_party_btn = _Element("end_party")
    confirm_btn = _Element("confirm_end")

    handler = _MockHandler(elements={
        "more_menu": more_menu_btn,
        "end_party": end_party_btn,
        "confirm_end": confirm_btn
    })
    manager = PartyService(
        driver=SoulPartyDriver(handler),
        room_state=RoomStateService(),
        logger=handler.logger,
    )
    manager._logger = handler.logger

    res = manager.end_party()

    assert more_menu_btn.clicked is True
    assert end_party_btn.clicked is True
    assert confirm_btn.clicked is True


def test_exit_guest_party_with_confirm_end():
    more_menu_btn = _Element("more_menu")
    end_party_btn = _Element("end_party")
    confirm_end_btn = _Element("confirm_end")

    handler = _MockHandler(elements={
        "more_menu": more_menu_btn,
        "end_party": end_party_btn,
        "confirm_end": confirm_end_btn,
    })
    manager = PartyService(
        driver=SoulPartyDriver(handler),
        room_state=RoomStateService(),
        logger=handler.logger,
    )

    res = manager.end_party()

    assert res == {'success': 'Party ended'}
    assert handler.switched is True
    assert more_menu_btn.clicked is True
    assert end_party_btn.clicked is True
    assert confirm_end_btn.clicked is True


def test_exit_guest_party_without_confirm_dialog():
    more_menu_btn = _Element("more_menu")
    end_party_btn = _Element("end_party")

    handler = _MockHandler(elements={
        "more_menu": more_menu_btn,
        "end_party": end_party_btn,
    })
    manager = PartyService(
        driver=SoulPartyDriver(handler),
        room_state=RoomStateService(),
        logger=handler.logger,
    )

    res = manager.end_party()

    assert res == {'success': 'Party ended'}
    assert handler.switched is True
    assert more_menu_btn.clicked is True
    assert end_party_btn.clicked is True







