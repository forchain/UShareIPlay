import pytest
from unittest.mock import MagicMock
from ushareiplay.core.ui.gesture_handler import GestureHandler

class FakeWebElement:
    def __init__(self, text):
        self._text = text
    
    @property
    def location(self):
        return {"x": 0, "y": 0}
    
    @property
    def size(self):
        return {"width": 100, "height": 100}

def test_scroll_container_until_element_down_chronological():
    owner = MagicMock()
    owner.logger = MagicMock()
    owner.config = {}
    
    def try_get_attribute(element, attr):
        if attr == "text":
            return element._text
        return None
    owner.try_get_attribute.side_effect = try_get_attribute
    
    gh = GestureHandler(owner)
    
    container = FakeWebElement("container")
    owner.wait_for_element_clickable.return_value = container
    
    gh._perform_swipe = MagicMock(return_value=True)
    
    owner.driver = MagicMock()
    page_sources = ["source0", "source1", "source2"]
    def get_page_source():
        if page_sources:
            return page_sources.pop(0)
        return "source_end"
    type(owner.driver).page_source = property(lambda self: get_page_source())
    
    # direction == "down" -> scrolling up in history.
    # So Round 1 has newest elements. Round 2 has older elements.
    view_1 = [FakeWebElement("msg_2"), FakeWebElement("msg_3")]  # Round 1 (bottom of chat)
    view_2 = [FakeWebElement("msg_1"), FakeWebElement("msg_2")]  # Round 2 (after 1 swipe)
    
    def find_child_element(parent, key):
        return MagicMock()
        
    owner.find_child_element.side_effect = find_child_element
    
    views = [view_1, view_2]
    def find_child_elements(parent, key):
        if views:
            return views.pop(0)
        return []
    owner.find_child_elements.side_effect = find_child_elements
    
    key, found_elem, attribute_values = gh.scroll_container_until_element(
        element_key="message_content",
        container_key="message_list",
        direction="down",
        attribute_name="text",
        attribute_value="msg_1",
        max_swipes=5
    )
    
    assert key == "message_content"
    assert attribute_values == ["msg_1", "msg_2", "msg_3"]

def test_scroll_container_until_element_up_chronological():
    owner = MagicMock()
    owner.logger = MagicMock()
    owner.config = {}
    
    def try_get_attribute(element, attr):
        if attr == "text":
            return element._text
        return None
    owner.try_get_attribute.side_effect = try_get_attribute
    
    gh = GestureHandler(owner)
    
    container = FakeWebElement("container")
    owner.wait_for_element_clickable.return_value = container
    
    gh._perform_swipe = MagicMock(return_value=True)
    
    owner.driver = MagicMock()
    page_sources = ["source0", "source1", "source2"]
    def get_page_source():
        if page_sources:
            return page_sources.pop(0)
        return "source_end"
    type(owner.driver).page_source = property(lambda self: get_page_source())
    
    # direction == "up" -> scrolling down in history.
    # So Round 1 has older elements. Round 2 has newer elements.
    view_1 = [FakeWebElement("line_1"), FakeWebElement("line_2")]
    view_2 = [FakeWebElement("line_2"), FakeWebElement("line_3")]
    
    def find_child_element(parent, key):
        return MagicMock()
    owner.find_child_element.side_effect = find_child_element
    
    views = [view_1, view_2]
    def find_child_elements(parent, key):
        if views:
            return views.pop(0)
        return []
    owner.find_child_elements.side_effect = find_child_elements
    
    key, found_elem, attribute_values = gh.scroll_container_until_element(
        element_key="message_content",
        container_key="message_list",
        direction="up",
        attribute_name="text",
        attribute_value="line_3",
        max_swipes=5
    )
    
    assert key == "message_content"
    assert attribute_values == ["line_1", "line_2", "line_3"]
