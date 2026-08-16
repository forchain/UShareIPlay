import pytest
from unittest.mock import MagicMock, patch
from ushareiplay.managers.party_manager import PartyManager
from ushareiplay.models import MessageInfo


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
    def __init__(self, name="", text=""):
        self.name = name
        self.text = text
        self.clicked = False
        self.keys = []

    def click(self):
        self.clicked = True

    def send_keys(self, value):
        self.keys.append(value)


class _MockHandler:
    def __init__(self, elements=None, config=None):
        self.config = config or {}
        self.logger = _Logger()
        self.elements = elements or {}
        self.child_elements = {}
        self.party_id = None
        self.grabbed_mic = False
        self.current_screen = 'room'  # 'room', 'more_menu', 'hall', 'search'

    def try_find_element(self, key, log=True):
        if self.current_screen == 'room' and key in ('party_hall', 'search_entry', 'parties_search'):
            return None
        if self.current_screen == 'more_menu' and key in ('search_entry', 'parties_search'):
            return None
        return self.elements.get(key)

    def wait_for_element(self, key):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key):
        return self.elements.get(key)

    def wait_for_any_element(self, keys, timeout=None):
        for k in keys:
            if k in self.elements and self.elements[k] is not None:
                return k, self.elements[k]
        return None, None

    def find_child_element(self, parent, key):
        return self.child_elements.get((parent, key))

    def grab_mic_and_confirm(self):
        self.grabbed_mic = True

    @property
    def element_finder(self):
        return self

    @property
    def key_actions(self):
        return self


@pytest.mark.asyncio
async def test_invite_user_target_party_not_found_does_not_close_current_room():
    """
    当目标房间未开启/搜索不到时：
    1. 不得点击 exit_room_btn 或 end_party 关闭当前房间
    2. 必须点击 floating_entry 安全返回原房间
    3. 返回包含 error 的字典
    """
    manager = PartyManager.instance()

    more_menu = _Element("more_menu")
    party_hall = _Element("party_hall")
    search_entry = _Element("search_entry")
    search_box = _Element("search_box")
    search_button = _Element("search_button")
    parties_search = _Element("parties_search")
    floating_entry = _Element("floating_entry")
    exit_room_btn = _Element("exit_room_btn")
    end_party = _Element("end_party")

    handler = _MockHandler(elements={
        "more_menu": more_menu,
        "party_hall": party_hall,
        "search_entry": search_entry,
        "search_box": search_box,
        "search_button": search_button,
        "parties_search": parties_search,
        "floating_entry": floating_entry,
        "exit_room_btn": exit_room_btn,
        "end_party": end_party,
    })
    # Target party element is NOT found under parties_search
    handler.child_elements = {}

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Alice", content=":room 999999")
    result = await manager.invite_user(msg, "999999")

    assert 'error' in result
    assert "999999" in result['error'] or result.get('party_id') == "999999"
    # Current room MUST NOT be closed!
    assert exit_room_btn.clicked is False
    assert end_party.clicked is False
    # Must navigate to hall, search target, and return via floating window
    assert more_menu.clicked is True
    assert party_hall.clicked is True
    assert search_entry.clicked is True
    assert "999999" in search_box.keys
    assert search_button.clicked is True
    assert floating_entry.clicked is True


@pytest.mark.asyncio
async def test_invite_user_with_minimize_room_button_found_and_switches():
    """
    当存在 minimize_room (ivChatZoomIn) 按钮时：
    1. 点击 minimize_room 最小化房间
    2. 进入搜索查找目标房间
    3. 找到目标房间并切换进入
    """
    manager = PartyManager.instance()

    minimize_room = _Element("minimize_room")
    search_entry = _Element("search_entry")
    search_box = _Element("search_box")
    search_button = _Element("search_button")
    parties_search = _Element("parties_search")
    party_item = _Element("party_id")

    handler = _MockHandler(elements={
        "minimize_room": minimize_room,
        "search_entry": search_entry,
        "search_box": search_box,
        "search_button": search_button,
        "parties_search": parties_search,
    })
    handler.child_elements = {
        (parties_search, 'party_id'): party_item
    }

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Alice", content=":room 555555")
    result = await manager.invite_user(msg, "555555")

    assert 'error' not in result
    assert result['party_id'] == "555555"
    assert minimize_room.clicked is True
    assert search_entry.clicked is True
    assert party_item.clicked is True
    assert handler.grabbed_mic is True
    assert handler.party_id == "555555"


@pytest.mark.asyncio
async def test_invite_user_target_party_closed_card_with_no_party_online_restores_room():
    """
    针对用户上报的具体线上场景：
    搜索 FM13515566 时，页面显示了 room_card（提示“派对已结束~”），但 party_online 不存在。
    此时系统必须判定为派对未开启，安全点击 floating_entry 返回原房间，并返回错误提示。
    """
    manager = PartyManager.instance()

    minimize_room = _Element("minimize_room")
    search_entry = _Element("search_entry")
    search_box = _Element("search_box")
    search_button = _Element("search_button")
    room_card = _Element("room_card", text="派对已结束~")
    floating_entry = _Element("floating_entry")

    handler = _MockHandler(elements={
        "minimize_room": minimize_room,
        "search_entry": search_entry,
        "search_box": search_box,
        "search_button": search_button,
        "room_card": room_card,
        # party_online is None because party is closed
        "party_online": None,
        "floating_entry": floating_entry,
    })

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Outlier", content=":room FM13515566")
    result = await manager.invite_user(msg, "FM13515566")

    assert 'error' in result
    assert result['party_id'] == 'FM13515566'
    assert room_card.clicked is False
    assert floating_entry.clicked is True




@pytest.mark.asyncio
async def test_invite_user_target_party_open_switches_successfully():
    """
    当目标房间确认开启时：
    1. 搜索并找到目标房间
    2. 点击进入目标房间
    3. 自动抢麦并更新 party_id
    4. 返回成功信息
    """
    manager = PartyManager.instance()

    more_menu = _Element("more_menu")
    party_hall = _Element("party_hall")
    search_entry = _Element("search_entry")
    search_box = _Element("search_box")
    search_button = _Element("search_button")
    parties_search = _Element("parties_search")
    party_item = _Element("party_id")

    handler = _MockHandler(elements={
        "more_menu": more_menu,
        "party_hall": party_hall,
        "search_entry": search_entry,
        "search_box": search_box,
        "search_button": search_button,
        "parties_search": parties_search,
    })
    handler.child_elements = {
        (parties_search, 'party_id'): party_item
    }

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Bob", content=":room 123456")
    result = await manager.invite_user(msg, "123456")

    assert 'error' not in result
    assert result['party_id'] == "123456"
    assert result['user'] == "Bob"
    assert party_item.clicked is True
    assert handler.grabbed_mic is True
    assert handler.party_id == "123456"


@pytest.mark.asyncio
async def test_invite_user_target_party_with_switch_confirmation_dialog():
    """
    当进入目标房间时弹出解散/退出当前房间确认弹窗时，应自动点击确认
    """
    manager = PartyManager.instance()

    more_menu = _Element("more_menu")
    party_hall = _Element("party_hall")
    search_entry = _Element("search_entry")
    search_box = _Element("search_box")
    search_button = _Element("search_button")
    parties_search = _Element("parties_search")
    party_item = _Element("party_id")
    confirm_end = _Element("confirm_end")

    handler = _MockHandler(elements={
        "more_menu": more_menu,
        "party_hall": party_hall,
        "search_entry": search_entry,
        "search_box": search_box,
        "search_button": search_button,
        "parties_search": parties_search,
        "confirm_end": confirm_end,
    })
    handler.child_elements = {
        (parties_search, 'party_id'): party_item
    }

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Carol", content=":room 888888")
    result = await manager.invite_user(msg, "888888")

    assert 'error' not in result
    assert result['party_id'] == "888888"
    assert party_item.clicked is True
    assert confirm_end.clicked is True
    assert handler.grabbed_mic is True
    assert handler.party_id == "888888"


@pytest.mark.asyncio
async def test_restore_current_party_fallback_with_search_back():
    """
    若悬浮窗在搜索页未直接找到，通过 search_back 后再找到并点击
    """
    manager = PartyManager.instance()

    search_back = _Element("search_back")
    floating_entry = _Element("floating_entry")

    class _FallbackHandler(_MockHandler):
        def __init__(self):
            super().__init__()
            self.backed = False

        def try_find_element(self, key, log=True):
            if key == 'search_back':
                return search_back
            return None

        def wait_for_any_element(self, keys, timeout=None):
            if self.backed and 'floating_entry' in keys:
                return 'floating_entry', floating_entry
            return None, None

    handler = _FallbackHandler()
    search_back.click = lambda: setattr(handler, 'backed', True)
    manager._handler = handler
    manager._logger = handler.logger

    restored = manager._restore_current_party()
    assert restored is True
    assert floating_entry.clicked is True


@pytest.mark.asyncio
async def test_restore_current_party_fallback_with_press_back():
    """
    若 search_back 亦不存在，使用 key_actions.press_back 兜底
    """
    manager = PartyManager.instance()

    floating_entry = _Element("floating_entry")

    class _PressBackHandler(_MockHandler):
        def __init__(self):
            super().__init__()
            self.press_backed = False

        def try_find_element(self, key, log=True):
            return None

        def press_back(self):
            self.press_backed = True

        def wait_for_any_element(self, keys, timeout=None):
            if self.press_backed and 'floating_entry' in keys:
                return 'floating_entry', floating_entry
            return None, None

    handler = _PressBackHandler()
    manager._handler = handler
    manager._logger = handler.logger

    restored = manager._restore_current_party()
    assert restored is True
    assert handler.press_backed is True
    assert floating_entry.clicked is True


@pytest.mark.asyncio
async def test_invite_user_missing_search_box_error():
    manager = PartyManager.instance()

    more_menu = _Element("more_menu")
    party_hall = _Element("party_hall")
    search_entry = _Element("search_entry")
    floating_entry = _Element("floating_entry")

    handler = _MockHandler(elements={
        "more_menu": more_menu,
        "party_hall": party_hall,
        "search_entry": search_entry,
        "search_box": None,  # Missing search box
        "floating_entry": floating_entry,
    })

    manager._handler = handler
    manager._logger = handler.logger

    msg = MessageInfo(nickname="Alice", content=":room 123456")
    result = await manager.invite_user(msg, "123456")

    assert 'error' in result
    assert result['party_id'] == '123456'
    assert floating_entry.clicked is True


@pytest.mark.asyncio
async def test_navigate_back_to_hall_entry_via_back_loop_to_planet_tab():
    """
    测试当最小化后处于子页面时，不断点击返回直到出现 planet_tab，随后进入 party_hall_entry
    """
    manager = PartyManager.instance()

    item_left_back = _Element("item_left_back")
    planet_tab = _Element("planet_tab")
    party_hall_entry = _Element("party_hall_entry")

    class _DeepScreenHandler(_MockHandler):
        def __init__(self):
            super().__init__()
            self.back_clicks = 0

        def try_find_element(self, key, log=True):
            if key == 'search_entry':
                return None
            if key == 'party_hall_entry':
                return party_hall_entry if planet_tab.clicked else None
            if key == 'planet_tab':
                return planet_tab if self.back_clicks >= 2 else None
            return None

        def wait_for_element_clickable(self, key):
            if key == 'party_hall_entry':
                return party_hall_entry
            return None

        def wait_for_any_element(self, keys, timeout=None):
            if self.back_clicks < 2 and 'item_left_back' in keys:
                return 'item_left_back', item_left_back
            return None, None

    handler = _DeepScreenHandler()

    def _on_back_click():
        item_left_back.clicked = True
        handler.back_clicks += 1

    item_left_back.click = _on_back_click

    manager._handler = handler
    manager._logger = handler.logger

    res = manager._navigate_back_to_hall_entry(max_attempts=5)
    assert res is True
    assert handler.back_clicks == 2
    assert planet_tab.clicked is True
    assert party_hall_entry.clicked is True


@pytest.mark.asyncio
async def test_navigate_back_to_hall_entry_via_party_tab():
    """
    测试直接检测到 party_tab 并成功进入搜索
    """
    manager = PartyManager.instance()

    party_tab = _Element("party_tab")
    search_entry = _Element("search_entry")

    class _PartyTabHandler(_MockHandler):
        def __init__(self):
            super().__init__()
            self.tab_clicked = False

        def try_find_element(self, key, log=True):
            if key == 'party_tab':
                return party_tab
            if key == 'search_entry':
                return search_entry if self.tab_clicked else None
            return None

    handler = _PartyTabHandler()

    def _on_tab_click():
        party_tab.clicked = True
        handler.tab_clicked = True

    party_tab.click = _on_tab_click

    manager._handler = handler
    manager._logger = handler.logger

    res = manager._navigate_back_to_hall_entry(max_attempts=3)
    assert res is True
    assert party_tab.clicked is True


