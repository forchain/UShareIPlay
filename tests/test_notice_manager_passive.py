from types import SimpleNamespace
from ushareiplay.managers.notice_manager import NoticeManager


class _Element:
    def __init__(self, text=""):
        self.text = text
        self.clicked = False
        self.cleared = False
        self.sent_text = None

    def click(self):
        self.clicked = True

    def clear(self):
        self.cleared = True

    def send_keys(self, text):
        self.sent_text = text


class _Handler:
    def __init__(self, elements=None):
        self.elements = elements or {}
        self.element_finder = self
        self.config = {
            'soul': {'system_default_notices': ['弹唱大会', 'Souler们在随便聊聊ing', '蹲一个人']},
            'default_notice': 'Custom Notice Test'
        }
        self.logger = SimpleNamespace(
            info=lambda _msg: None,
            warning=lambda _msg: None,
            error=lambda _msg: None
        )

    def try_find_element(self, key, log=False):
        return self.elements.get(key)

    def get_element_text(self, element):
        return getattr(element, 'text', '')

    def wait_for_element(self, key):
        return self.elements.get(key)

    def wait_for_element_clickable(self, key):
        return self.elements.get(key)

    def wait_for_any_element(self, keys):
        for k in keys:
            if k in self.elements:
                return k, self.elements[k]
        return None, None


def test_sync_and_correct_notice_if_dialog_open_detects_reset():
    NoticeManager.reset_instance()
    manager = NoticeManager.initialize()

    edit_entry = _Element(text="蹲一个人 蹲了那么久，终于等到你！")
    close_notice = _Element()
    customize_btn = _Element()
    input_elem = _Element()
    confirm_btn = _Element()

    handler = _Handler(elements={
        'edit_notice_entry': edit_entry,
        'close_notice': close_notice,
        'customize_notice_button': customize_btn,
        'edit_notice_input': input_elem,
        'edit_notice_confirm': confirm_btn,
    })
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.sync_and_correct_notice_if_dialog_open()

    assert res.get('success') is True
    assert edit_entry.clicked is True
    assert customize_btn.clicked is True
    assert input_elem.sent_text == 'Custom Notice Test'
    assert confirm_btn.clicked is True


def test_sync_and_correct_notice_if_dialog_open_skips_when_normal():
    NoticeManager.reset_instance()
    manager = NoticeManager.initialize()

    edit_entry = _Element(text="Welcome to my singing room")
    handler = _Handler(elements={'edit_notice_entry': edit_entry})
    manager._handler = handler
    manager._logger = handler.logger

    res = manager.sync_and_correct_notice_if_dialog_open()

    assert res.get('status') == 'notice_normal'
    assert edit_entry.clicked is False
