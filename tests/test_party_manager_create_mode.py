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
    def __init__(self, config, any_results=None):
        self.config = config
        self.logger = _Logger()
        self._any_results = any_results or []

    def wait_for_any_element_plus(self, _keys):
        return self._any_results.pop(0)

    def wait_for_element_plus(self, key):
        if key == 'party_state_entry':
            return _Element()
        if key == 'close_party_notification':
            return _Element()
        if key == 'create_party_button':
            return _Element()
        return None


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
