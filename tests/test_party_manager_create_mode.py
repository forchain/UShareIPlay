from ushareiplay.managers.party_manager import PartyManager


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
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class _Handler:
    def __init__(self, config, any_results=None, elements=None):
        self.config = config
        self.logger = _Logger()
        self._any_results = any_results or []
        self._elements = elements if elements is not None else {
            'party_state_entry': _Element(),
            'close_party_notification': _Element(),
            'party_type_chat': _Element(),
            'party_type_singing': _Element(),
            'create_party_button': _Element(),
        }

    def wait_for_any_element(self, _keys):
        return self._any_results.pop(0)

    def wait_for_element(self, key, *args, **kwargs):
        return self._elements.get(key)

    def wait_for_element_clickable(self, key, *args, **kwargs):
        return self._elements.get(key)

    def wait_for_element_disappear(self, key, *args, **kwargs):
        return True

    def try_find_element(self, key, *args, **kwargs):
        return self._elements.get(key)

    @property
    def element_finder(self):
        return self


def test_party_create_mode_restore_clicks_restore_only():
    manager = PartyManager.instance()
    create_entry = _Element()
    restore_entry = _Element()
    handler = _Handler(
        config={"party_create_mode": "restore_party"},
        any_results=[
            ("create_party_entry", create_entry),
            ("restore_party", restore_entry),
        ],
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert create_entry.clicked is True
    assert restore_entry.clicked is True


def test_party_create_mode_default_keeps_new_flow():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    handler = _Handler(
        config={},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert create_entry.clicked is True
    assert new_entry.clicked is True


def test_restore_mode_with_confirm_party_keeps_legacy_flow():
    manager = PartyManager.instance()
    create_entry = _Element()
    confirm_entry = _Element()
    handler = _Handler(
        config={"party_create_mode": "restore_party"},
        any_results=[
            ("create_party_entry", create_entry),
            ("confirm_party", confirm_entry),
        ],
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert create_entry.clicked is True
    assert confirm_entry.clicked is True


def test_party_create_flow_switches_room_type_to_singing():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    chat_type_entry = _Element()
    singing_type_entry = _Element()
    create_party_btn = _Element()

    elements = {
        'party_state_entry': _Element(),
        'party_type_chat': chat_type_entry,
        'party_type_singing': singing_type_entry,
        'create_party_button': create_party_btn,
    }
    handler = _Handler(
        config={"change_party_type": True},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert chat_type_entry.clicked is True
    assert singing_type_entry.clicked is True
    assert create_party_btn.clicked is True


def test_party_create_flow_fails_when_party_type_chat_not_found():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()

    elements = {
        'party_state_entry': _Element(),
        'party_type_chat': None,
        'party_type_singing': _Element(),
        'create_party_button': _Element(),
    }
    handler = _Handler(
        config={"change_party_type": True},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is False


def test_party_create_flow_fails_when_party_type_singing_not_found():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    chat_type_entry = _Element()

    elements = {
        'party_state_entry': _Element(),
        'party_type_chat': chat_type_entry,
        'party_type_singing': None,
        'create_party_button': _Element(),
    }
    handler = _Handler(
        config={"change_party_type": True},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is False
    assert chat_type_entry.clicked is True


def test_party_create_flow_skips_room_type_change_when_disabled():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    chat_type_entry = _Element()
    singing_type_entry = _Element()
    create_party_btn = _Element()

    elements = {
        'party_state_entry': _Element(),
        'party_type_chat': chat_type_entry,
        'party_type_singing': singing_type_entry,
        'create_party_button': create_party_btn,
    }
    handler = _Handler(
        config={"change_party_type": False},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert chat_type_entry.clicked is False
    assert singing_type_entry.clicked is False
    assert create_party_btn.clicked is True


def test_party_create_flow_disables_recommendation_and_waits_disappear():
    from ushareiplay.state.room_state import RoomState
    RoomState.initialize()
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    party_state_entry = _Element()
    close_party_notification = _Element()
    chat_type_entry = _Element()
    singing_type_entry = _Element()
    create_party_btn = _Element()

    disappeared = []

    class _DisappearHandler(_Handler):
        def wait_for_element_disappear(self, key, *args, **kwargs):
            disappeared.append(key)
            return True

    elements = {
        'party_state_entry': party_state_entry,
        'close_party_notification': close_party_notification,
        'party_type_chat': chat_type_entry,
        'party_type_singing': singing_type_entry,
        'create_party_button': create_party_btn,
    }
    handler = _DisappearHandler(
        config={"create_party_recommendation": False, "change_party_type": True},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert party_state_entry.clicked is True
    assert close_party_notification.clicked is True
    assert 'close_party_notification' in disappeared
    assert 'party_type_singing' in disappeared
    assert RoomState.instance().recommendation_enabled is False


def test_party_create_flow_retries_and_succeeds_when_first_type_click_misses():
    manager = PartyManager.instance()
    create_entry = _Element()
    new_entry = _Element()
    chat_type_entry = _Element()
    singing_type_entry = _Element()
    create_party_btn = _Element()

    attempt_count = 0

    class _RetryHandler(_Handler):
        def wait_for_element(self, key, *args, **kwargs):
            nonlocal attempt_count
            if key == 'party_type_singing':
                attempt_count += 1
                if attempt_count == 1:
                    # First click was swallowed/dropped, menu not open
                    return None
                return singing_type_entry
            return self._elements.get(key)

    elements = {
        'party_state_entry': _Element(),
        'party_type_chat': chat_type_entry,
        'party_type_singing': singing_type_entry,
        'create_party_button': create_party_btn,
    }
    handler = _RetryHandler(
        config={"change_party_type": True},
        any_results=[
            ("create_party_entry", create_entry),
            ("new_party_entry", new_entry),
        ],
        elements=elements,
    )
    manager._handler = handler
    manager._logger = handler.logger

    ok = manager._create_party_flow()

    assert ok is True
    assert attempt_count == 2
    assert singing_type_entry.clicked is True
    assert create_party_btn.clicked is True


