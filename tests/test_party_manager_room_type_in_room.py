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
    def __init__(self, text=""):
        self.text = text
        self.clicked = False

    def click(self):
        self.clicked = True


class _KeyActions:
    def __init__(self):
        self.back_presses = 0

    def press_back(self):
        self.back_presses += 1


class _Handler:
    def __init__(self, config=None, elements=None):
        self.config = config or {}
        self.logger = _Logger()
        self.key_actions = _KeyActions()
        self._elements = elements or {}

    def wait_for_element(self, key):
        return self._elements.get(key)

    def wait_for_element_clickable(self, key):
        return self._elements.get(key)

    def try_find_element(self, key, log=False):
        return self._elements.get(key)

    @property
    def element_finder(self):
        return self


def test_check_and_correct_room_type_switches_when_chat():
    manager = PartyManager.instance()
    type_option = _Element(text="闲聊唠嗑")
    singing_option = _Element(text="唱歌听歌")

    elements = {
        'party_room_type_option': type_option,
        'party_type_singing': singing_option,
    }
    handler = _Handler(config={}, elements=elements)
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.check_and_correct_room_type(auto_close=True)

    assert res.get('success') is True
    assert res.get('switched') is True
    assert type_option.clicked is True
    assert singing_option.clicked is True


def test_check_and_correct_room_type_skips_when_already_singing():
    manager = PartyManager.instance()
    type_option = _Element(text="唱歌听歌")
    singing_option = _Element(text="唱歌听歌")

    elements = {
        'party_room_type_option': type_option,
        'party_type_singing': singing_option,
    }
    handler = _Handler(config={}, elements=elements)
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.check_and_correct_room_type(auto_close=True)

    assert res.get('success') is True
    assert res.get('switched') is False
    assert type_option.clicked is False
    assert singing_option.clicked is False


def test_check_and_correct_room_type_opens_dialog_if_not_initially_visible():
    manager = PartyManager.instance()
    room_topic = _Element()
    type_option = _Element(text="闲聊唠嗑")
    singing_option = _Element(text="唱歌听歌")

    # Initially party_room_type_option is None until room_topic is clicked
    state = {'opened': False}

    class _DynamicHandler(_Handler):
        def try_find_element(self, key, log=False):
            if key == 'party_room_type_option':
                return type_option if state['opened'] else None
            return super().try_find_element(key, log=log)

        def wait_for_element(self, key):
            if key == 'party_room_type_option':
                return type_option if state['opened'] else None
            return super().wait_for_element(key)

    def on_room_topic_click():
        room_topic.clicked = True
        state['opened'] = True

    room_topic.click = on_room_topic_click

    elements = {
        'room_topic': room_topic,
        'party_type_singing': singing_option,
    }
    handler = _DynamicHandler(config={}, elements=elements)
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.check_and_correct_room_type(auto_close=True)

    assert res.get('success') is True
    assert room_topic.clicked is True
    assert singing_option.clicked is True


def test_ensure_room_info_window_closed_presses_back_until_closed():
    manager = PartyManager.instance()
    remaining = {'count': 2}

    class _DynamicHandler(_Handler):
        def try_find_element(self, key, log=False):
            if key in ('party_room_type_option', 'party_recommendation_status'):
                if remaining['count'] > 0:
                    return _Element()
            return None

    handler = _DynamicHandler()
    
    def on_press_back():
        handler.key_actions.back_presses += 1
        remaining['count'] -= 1

    handler.key_actions.press_back = on_press_back

    manager._handler = handler
    manager._logger = handler.logger

    manager.ensure_room_info_window_closed()

    assert handler.key_actions.back_presses == 2


def test_ensure_room_info_window_closed_detects_notice_edit():
    manager = PartyManager.instance()
    remaining = {'count': 1}

    class _DynamicHandler(_Handler):
        def try_find_element(self, key, log=False):
            if key == 'edit_notice_entry':
                if remaining['count'] > 0:
                    return _Element()
            return None

    handler = _DynamicHandler()

    def on_press_back():
        handler.key_actions.back_presses += 1
        remaining['count'] -= 1

    handler.key_actions.press_back = on_press_back

    manager._handler = handler
    manager._logger = handler.logger

    manager.ensure_room_info_window_closed()

    assert handler.key_actions.back_presses == 1


def test_sync_and_correct_room_type_if_dialog_open_when_open():
    manager = PartyManager.instance()
    type_option = _Element(text="闲聊唠嗑")
    singing_option = _Element(text="唱歌听歌")

    elements = {
        'party_room_type_option': type_option,
        'party_type_singing': singing_option,
    }
    handler = _Handler(config={}, elements=elements)
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.sync_and_correct_room_type_if_dialog_open()

    assert res.get('success') is True
    assert res.get('switched') is True
    assert handler.key_actions.back_presses == 0


def test_sync_and_correct_room_type_if_dialog_open_when_not_open():
    manager = PartyManager.instance()
    room_topic = _Element()
    elements = {
        'room_topic': room_topic,
    }
    handler = _Handler(config={}, elements=elements)
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.sync_and_correct_room_type_if_dialog_open()

    assert res.get('skipped') is True
    assert res.get('reason') == 'dialog_not_open'
    assert room_topic.clicked is False


