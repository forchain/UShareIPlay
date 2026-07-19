import asyncio

from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.events.party_name_violation_later import PartyNameViolationLaterEvent
from ushareiplay.managers.title_manager import TitleManager


class _Logger:
    def __init__(self):
        self.info_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.info_messages.append(message)

    def error(self, message):
        self.info_messages.append(message)


class _Element:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class _Handler:
    def __init__(self, element):
        self.logger = _Logger()
        self.controller = object()
        self.element_finder = type("Finder", (), {"wait_for_element_clickable": lambda _self, _key: element})()


class _Snapshot:
    def __init__(self, text):
        self._text = text

    def context_text(self):
        return self._text


def test_element_wrapper_context_text_includes_dialog_siblings():
    root = etree.fromstring(
        "<hierarchy><dialog><label text='派对名称涉嫌违规'/><button resource-id='tvLater' text='稍后再说'/></dialog></hierarchy>"
    )
    wrapper = ElementWrapper(root.xpath("//*[@resource-id='tvLater']")[0])

    assert "派对名称涉嫌违规" in wrapper.context_text()


def test_non_violation_later_dialog_is_dismissed_without_resetting_title(monkeypatch):
    element = _Element()
    queued_titles = []
    monkeypatch.setattr(TitleManager, "instance", lambda: type("Title", (), {"set_next_title": queued_titles.append})())
    event = PartyNameViolationLaterEvent(_Handler(element))

    handled = asyncio.run(event.handle("party_name_violation_later", _Snapshot("活动提醒\n稍后再说")))

    assert handled is True
    assert element.clicked is True
    assert queued_titles == []


def test_confirmed_party_name_violation_queues_daily_title(monkeypatch):
    element = _Element()
    queued_titles = []
    monkeypatch.setattr(TitleManager, "instance", lambda: type("Title", (), {"set_next_title": queued_titles.append})())
    event = PartyNameViolationLaterEvent(_Handler(element))

    handled = asyncio.run(event.handle("party_name_violation_later", _Snapshot("派对名称涉嫌违规，请修改后重试\n稍后再说")))

    assert handled is True
    assert element.clicked is True
    assert queued_titles == ["日推"]
