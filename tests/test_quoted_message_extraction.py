"""Quoted Message extraction from the chat UI hierarchy (issue #312)."""

from collections import deque
from unittest.mock import MagicMock, patch

import pytest
import yaml
from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper, composed_message_text
from ushareiplay.events.message_content import MessageContentEvent

MESSAGE_CONTENT_SELECTOR_KEY = "message_content"

_QUOTED_ROW_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyContent"
            text="Alice：今天天气不错" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Bob]说：哈哈" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_PLAIN_ROW_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Carol]说：在的" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_MIXED_ROWS_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyContent"
            text="Alice：今天天气不错" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Bob]说：哈哈" />
    </android.view.ViewGroup>
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Carol]说：在的" />
    </android.view.ViewGroup>
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyContent"
            text="Dave：晚安" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Erin]说：拜拜" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_NESTED_QUOTED_ROW_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyContent"
            text="Alice：今天天气不错" />
      </android.view.ViewGroup>
      <android.view.ViewGroup class="android.widget.FrameLayout">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
            text="souler[Bob]说：哈哈" />
      </android.view.ViewGroup>
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_REPLY_VIEW_WITHOUT_CONTENT_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyTip"
            text="回复" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Bob]说：哈哈" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_REPLY_CONTENT_IN_CONTENT_DESC_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/gReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/tvReplyContent"
            content-desc="Alice：今天天气不错" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/tvContent"
          text="souler[Bob]说：哈哈" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""


_CUSTOM_IDS_MIXED_ROWS_XML = """
<hierarchy rotation="0">
  <androidx.recyclerview.widget.RecyclerView
      resource-id="cn.soulapp.android:id/rvMessage">
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.view.ViewGroup resource-id="cn.soulapp.android:id/customReplyView">
        <android.widget.TextView resource-id="cn.soulapp.android:id/customReplyContent"
            text="Alice：今天天气不错" />
      </android.view.ViewGroup>
      <android.widget.TextView resource-id="cn.soulapp.android:id/customContent"
          text="souler[Bob]说：哈哈" />
    </android.view.ViewGroup>
    <android.view.ViewGroup resource-id="cn.soulapp.android:id/contentContainer">
      <android.widget.TextView resource-id="cn.soulapp.android:id/customContent"
          text="souler[Carol]说：在的" />
    </android.view.ViewGroup>
  </androidx.recyclerview.widget.RecyclerView>
</hierarchy>
"""

_CUSTOM_ID_CONFIG = {
    "soul": {
        "elements": {
            "message_reply_view": "cn.soulapp.android:id/customReplyView",
            "message_reply_content": "cn.soulapp.android:id/customReplyContent",
        }
    }
}


def _message_content_selector() -> str:
    with open("config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    return config["soul"]["elements"][MESSAGE_CONTENT_SELECTOR_KEY]


def _content_wrappers(page_source: str) -> list[ElementWrapper]:
    """Mirror EventManager: wrap every node matched by the message_content anchor."""
    root = etree.fromstring(page_source.encode("utf-8"))
    return [ElementWrapper(node) for node in root.xpath(_message_content_selector())]


def _custom_id_wrappers():
    handler = MagicMock()
    handler.config = _CUSTOM_ID_CONFIG
    root = etree.fromstring(_CUSTOM_IDS_MIXED_ROWS_XML.encode("utf-8"))
    nodes = root.xpath("//*[@resource-id='cn.soulapp.android:id/customContent']")
    return [ElementWrapper(node, handler) for node in nodes]


class TestQuotedMessageExtraction:
    def test_quoted_message_is_attached_to_sender_content(self):
        wrapper = _content_wrappers(_QUOTED_ROW_XML)[0]

        assert wrapper.quoted_message() == "Alice：今天天气不错"
        assert (
            composed_message_text(wrapper)
            == "souler[Bob]说：「Alice：今天天气不错」 哈哈"
        )

    def test_message_without_reply_view_is_unchanged(self):
        wrapper = _content_wrappers(_PLAIN_ROW_XML)[0]

        assert wrapper.quoted_message() is None
        assert composed_message_text(wrapper) == "souler[Carol]说：在的"

    def test_quote_is_found_across_an_intermediate_wrapper(self):
        wrapper = _content_wrappers(_NESTED_QUOTED_ROW_XML)[0]

        assert wrapper.quoted_message() == "Alice：今天天气不错"

    def test_quote_comes_from_reply_content_content_desc(self):
        wrapper = _content_wrappers(_REPLY_CONTENT_IN_CONTENT_DESC_XML)[0]

        assert wrapper.quoted_message() == "Alice：今天天气不错"

    def test_reply_view_without_reply_content_is_ignored(self):
        wrapper = _content_wrappers(_REPLY_VIEW_WITHOUT_CONTENT_XML)[0]

        assert wrapper.quoted_message() is None
        assert composed_message_text(wrapper) == "souler[Bob]说：哈哈"

    def test_neighbouring_rows_do_not_leak_their_quote(self):
        wrappers = _content_wrappers(_MIXED_ROWS_XML)

        assert [wrapper.quoted_message() for wrapper in wrappers] == [
            "Alice：今天天气不错",
            None,
            "Dave：晚安",
        ]
        assert [composed_message_text(wrapper) for wrapper in wrappers] == [
            "souler[Bob]说：「Alice：今天天气不错」 哈哈",
            "souler[Carol]说：在的",
            "souler[Erin]说：「Dave：晚安」 拜拜",
        ]

    def test_message_content_anchor_matches_every_row(self):
        # The anchor must keep matching quoted and unquoted rows alike so that
        # InChatReady room-readiness classification is unaffected.
        wrappers = _content_wrappers(_MIXED_ROWS_XML)

        assert len(wrappers) == 3
        assert [wrapper.text for wrapper in wrappers] == [
            "souler[Bob]说：哈哈",
            "souler[Carol]说：在的",
            "souler[Erin]说：拜拜",
        ]


class TestQuotedMessageSelectors:
    def test_reply_view_selectors_are_read_from_config(self):
        first, second = _custom_id_wrappers()

        assert first.quoted_message() == "Alice：今天天气不错"
        assert composed_message_text(first) == (
            "souler[Bob]说：「Alice：今天天气不错」 哈哈"
        )
        # Row guard must work off the element's own resource-id, not a fixed
        # message-content id, so other rows still cannot leak their quote.
        assert second.quoted_message() is None
        assert composed_message_text(second) == "souler[Carol]说：在的"

    def test_default_selectors_apply_without_a_configured_handler(self):
        root = etree.fromstring(_CUSTOM_IDS_MIXED_ROWS_XML.encode("utf-8"))
        nodes = root.xpath("//*[@resource-id='cn.soulapp.android:id/customContent']")

        assert [ElementWrapper(node).quoted_message() for node in nodes] == [None, None]


class TestMessageTextFallback:
    def test_non_element_wrapper_keeps_plain_content(self):
        class _FakeWrapper:
            content = "souler[Alice]说：hello"

        assert composed_message_text(_FakeWrapper()) == "souler[Alice]说：hello"

    def test_empty_content_stays_empty(self):
        class _FakeWrapper:
            content = ""

        assert composed_message_text(_FakeWrapper()) == ""


@pytest.mark.asyncio
async def test_message_content_event_logs_the_composed_quoted_message():
    handler = MagicMock()
    handler.logger = MagicMock()
    handler.config = {"soul": {"room_owner": "Joyer"}}
    event = MessageContentEvent(handler)

    message_manager = MagicMock()
    message_manager.latest_chats = deque(maxlen=3)
    message_manager.recent_chats = deque(maxlen=3)
    chat_logger = MagicMock()

    wrappers = _content_wrappers(_MIXED_ROWS_XML)
    with (
        patch(
            "ushareiplay.managers.message_manager.MessageManager.instance",
            return_value=message_manager,
        ),
        patch(
            "ushareiplay.managers.message_manager.get_chat_logger",
            return_value=chat_logger,
        ),
        patch("ushareiplay.managers.command_manager.CommandManager.instance"),
    ):
        await event.handle("message_content", wrappers)

    assert [call.args[0] for call in chat_logger.info.call_args_list] == list(
        message_manager.recent_chats
    )
    assert list(message_manager.recent_chats) == [
        "souler[Bob]说：「Alice：今天天气不错」 哈哈",
        "souler[Carol]说：在的",
        "souler[Erin]说：「Dave：晚安」 拜拜",
    ]
