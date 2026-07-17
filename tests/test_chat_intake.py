import pytest

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    ChatIntakeResult,
    classify_chat_line,
    expand_queue_text,
)


class TestClassifyChatLine:
    def test_command_with_ascii_colon(self):
        result = classify_chat_line("souler[Alice]说：:play 123")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.COMMAND,
            nickname="Alice",
            text=":play 123",
            trigger=":",
            silent=False,
            private_reply=False,
            raw="souler[Alice]说：:play 123",
        )

    def test_command_with_fullwidth_colon(self):
        result = classify_chat_line("souler[Alice]说：：play 123")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.COMMAND,
            nickname="Alice",
            text="：play 123",
            trigger="：",
            silent=False,
            private_reply=False,
            raw="souler[Alice]说：：play 123",
        )

    def test_silent_command_with_slash(self):
        result = classify_chat_line("souler[Alice]说：/timer list")
        assert result.kind == ChatIntakeKind.COMMAND
        assert result.text == "/timer list"
        assert result.trigger == "/"
        assert result.silent is True
        assert result.private_reply is False

    def test_private_command_with_dollar(self):
        result = classify_chat_line("souler[Alice]说：$info")
        assert result.kind == ChatIntakeKind.COMMAND
        assert result.text == "$info"
        assert result.trigger == "$"
        assert result.silent is False
        assert result.private_reply is True

    def test_private_command_with_fullwidth_dollar(self):
        result = classify_chat_line("souler[Alice]说：＄info")
        assert result.kind == ChatIntakeKind.COMMAND
        assert result.text == "＄info"
        assert result.trigger == "＄"
        assert result.silent is False
        assert result.private_reply is True

    def test_command_with_trigger_only_content_has_empty_text(self):
        # Matches legacy behavior: trigger with no payload yields an empty text
        # but is still classified as a command. Callers filter these out.
        result = classify_chat_line("souler[Alice]说：:   ")
        assert result.kind == ChatIntakeKind.COMMAND
        assert result.text == ""
        assert result.trigger == ":"

    def test_keyword_mention(self):
        result = classify_chat_line("souler[Alice]说：@我 播放 周杰伦 稻香")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="播放",
            params="周杰伦 稻香",
            raw="souler[Alice]说：@我 播放 周杰伦 稻香",
        )

    def test_keyword_mention_without_params(self):
        result = classify_chat_line("souler[Alice]说：@我 帮助")
        assert result.kind == ChatIntakeKind.KEYWORD_MENTION
        assert result.text == "帮助"
        assert result.params == ""

    def test_user_return_with_enter_wording(self):
        result = classify_chat_line("Alice进来陪你聊天啦")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Alice"
        assert result.text == "Alice"

    def test_user_return_with_seated_wording(self):
        result = classify_chat_line("Alice坐着飞船来啦")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Alice"
        assert result.text == "Alice"

    def test_plain_chat_with_wrapper(self):
        result = classify_chat_line("souler[Alice]说：hello world")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.PLAIN_CHAT,
            nickname="Alice",
            text="hello world",
            raw="souler[Alice]说：hello world",
        )

    def test_plain_chat_without_wrapper(self):
        result = classify_chat_line("just some system text")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.nickname == ""
        assert result.text == "just some system text"

    def test_empty_input(self):
        result = classify_chat_line("")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == ""

    def test_frozen_result_cannot_be_mutated(self):
        result = classify_chat_line("souler[Alice]说：:play 123")
        with pytest.raises(AttributeError):
            result.text = "mutated"


class TestExpandQueueText:
    def test_splits_plain_and_command_parts(self):
        results = expand_queue_text("hello {user_name};:timer list", "Alice")
        assert len(results) == 2
        assert results[0] == ChatIntakeResult(
            kind=ChatIntakeKind.PLAIN_CHAT,
            nickname="Alice",
            text="hello Alice",
            silent=False,
            sleep_exempt=False,
            raw="hello Alice",
        )
        assert results[1] == ChatIntakeResult(
            kind=ChatIntakeKind.COMMAND,
            nickname="Alice",
            text=":timer list",
            trigger=":",
            silent=False,
            private_reply=False,
            sleep_exempt=False,
            raw=":timer list",
        )

    def test_inherited_silent_flag(self):
        results = expand_queue_text("hello", "Alice", silent=True)
        assert len(results) == 1
        assert results[0].kind == ChatIntakeKind.PLAIN_CHAT
        assert results[0].silent is True

    def test_inherited_sleep_exempt_flag(self):
        results = expand_queue_text(":mode random;:playlist Sugar", "Alice", sleep_exempt=True)
        assert [r.sleep_exempt for r in results] == [True, True]

    def test_slash_part_is_silent_command(self):
        results = expand_queue_text("hello;/timer list", "Alice")
        assert results[0].kind == ChatIntakeKind.PLAIN_CHAT
        assert results[1].kind == ChatIntakeKind.COMMAND
        assert results[1].silent is True

    def test_dollar_part_is_private_command(self):
        results = expand_queue_text("hello;$info", "Alice")
        assert results[1].kind == ChatIntakeKind.COMMAND
        assert results[1].private_reply is True
        assert results[1].silent is False

    def test_fullwidth_dollar_part(self):
        results = expand_queue_text("＄info", "Alice")
        assert len(results) == 1
        assert results[0].text == "＄info"
        assert results[0].private_reply is True

    def test_silent_inherited_overrides_plain_part_only(self):
        results = expand_queue_text("hello", "Alice", silent=True)
        assert results[0].silent is True

    def test_empty_and_whitespace_parts_are_skipped(self):
        results = expand_queue_text("hello ;  ; ;world", "Alice")
        assert [r.text for r in results] == ["hello", "world"]

    def test_plain_part_does_not_get_private_reply(self):
        results = expand_queue_text("hello", "Alice")
        assert results[0].private_reply is False

    def test_fullwidth_slash_is_silent_command(self):
        results = expand_queue_text("／timer list", "Alice")
        assert results[0].kind == ChatIntakeKind.COMMAND
        assert results[0].silent is True
        assert results[0].trigger == "／"


class TestQueueCommandPrefixChars:
    def test_includes_all_triggers(self):
        assert QUEUE_COMMAND_PREFIX_CHARS == ":：/／$＄"
