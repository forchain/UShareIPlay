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

    def test_gift_type1_matches_when_receiver_is_room_owner(self):
        result = classify_chat_line("souler[🍻🥂🥃🍸🍷🍺]送给Joyer", room_owner="Joyer")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "🍻🥂🥃🍸🍷🍺"
        assert result.text == "🍻🥂🥃🍸🍷🍺"
        assert result.heat_value == 0

    def test_gift_type1_matches_with_trailing_gift_name(self):
        result = classify_chat_line("souler[🍻🥂🥃🍸🍷🍺]送给Joyer 【为你爆灯】", room_owner="Joyer")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "🍻🥂🥃🍸🍷🍺"
        assert result.heat_value == 0

    def test_gift_type1_matches_with_spaces(self):
        result = classify_chat_line("souler[🍻🥂🥃🍸🍷🍺] 送给 Joyer 【为你爆灯】", room_owner="Joyer")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "🍻🥂🥃🍸🍷🍺"
        assert result.heat_value == 0

    def test_gift_type1_ignored_when_receiver_is_not_room_owner(self):
        result = classify_chat_line("souler[Alice]送给Bob", room_owner="Joyer")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT

    def test_gift_type2_heat_contribution_matches(self):
        result = classify_chat_line("08-02 17:44:58 [I] 恭喜🍻🥂🥃🍸🍷🍺在此房间贡献出3120热力值")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "🍻🥂🥃🍸🍷🍺"
        assert result.text == "🍻🥂🥃🍸🍷🍺"
        assert result.heat_value == 3120

    def test_gift_type2_heat_contribution_with_spaces(self):
        result = classify_chat_line("08-22 15:23:48 [W] 恭喜 dio🤐 在此房间贡献出 11667热力值")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "dio🤐"
        assert result.text == "dio🤐"
        assert result.heat_value == 11667

    def test_gift_type2_heat_contribution_large_value(self):
        result = classify_chat_line("恭喜Alice在此房间贡献出1000000热力值")
        assert result.kind == ChatIntakeKind.GIFT_RECEIVE
        assert result.nickname == "Alice"
        assert result.heat_value == 1000000

    def test_keyword_mention_with_room_owner_name(self):
        result = classify_chat_line("souler[Alice]说：@Chainer 播放 周杰伦 稻香", room_owner="Chainer")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="播放",
            params="周杰伦 稻香",
            raw="souler[Alice]说：@Chainer 播放 周杰伦 稻香",
        )

    def test_keyword_mention_with_room_owner_natural_language(self):
        result = classify_chat_line("souler[Alice]说: @Chainer 帮我放一首晴天", room_owner="Chainer")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="帮我放一首晴天",
            params="",
            raw="souler[Alice]说: @Chainer 帮我放一首晴天",
        )

    def test_keyword_mention_matches_wo_even_when_room_owner_set(self):
        result = classify_chat_line("souler[Alice]说：@我 帮助", room_owner="Chainer")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="帮助",
            params="",
            raw="souler[Alice]说：@我 帮助",
        )

    def test_keyword_mention_with_other_user_is_plain_chat(self):
        result = classify_chat_line("souler[Alice]说：@Bob 播放 周杰伦 稻香", room_owner="Chainer")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.PLAIN_CHAT,
            nickname="Alice",
            text="@Bob 播放 周杰伦 稻香",
            raw="souler[Alice]说：@Bob 播放 周杰伦 稻香",
        )

    def test_keyword_mention_with_special_chars_in_room_owner(self):
        result = classify_chat_line("souler[Alice]说: @C++_Pro(Boss) 晴天", room_owner="C++_Pro(Boss)")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="晴天",
            params="",
            raw="souler[Alice]说: @C++_Pro(Boss) 晴天",
        )

    # --- @mention at any position ---

    def test_keyword_mention_at_wo_at_middle(self):
        """@我 in the middle of the message should be recognized."""
        result = classify_chat_line("souler[Alice]说：帮我 @我 播放 周杰伦 稻香")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="播放",
            params="周杰伦 稻香",
            raw="souler[Alice]说：帮我 @我 播放 周杰伦 稻香",
        )

    def test_keyword_mention_owner_at_middle(self):
        """@owner in the middle of the message should be recognized."""
        result = classify_chat_line(
            "souler[Alice]说：帮我 @Chainer 播放 周杰伦 稻香", room_owner="Chainer"
        )
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="播放",
            params="周杰伦 稻香",
            raw="souler[Alice]说：帮我 @Chainer 播放 周杰伦 稻香",
        )

    def test_keyword_mention_owner_no_trailing_space_is_plain_chat(self):
        """@ownerXXX with no space after owner name must NOT be recognized (粘连)."""
        result = classify_chat_line(
            "souler[Alice]说：@Chainerxxx播放", room_owner="Chainer"
        )
        assert result.kind == ChatIntakeKind.PLAIN_CHAT

    def test_keyword_mention_wo_no_trailing_space_at_middle_is_plain_chat(self):
        """@我xxx with no space after 我 in the middle must NOT be recognized."""
        result = classify_chat_line("souler[Alice]说：帮我@我xxx播放")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT

    def test_keyword_mention_owner_at_end_no_content_is_plain_chat(self):
        """@owner alone with no preceding content is NOT a keyword mention."""
        result = classify_chat_line("souler[Alice]说：@Chainer", room_owner="Chainer")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT

    def test_keyword_mention_owner_at_end_with_preceding_content(self):
        """@owner at the very end with preceding text extracts that text as keyword."""
        result = classify_chat_line(
            "souler[Joyer]说：房间有哪些人@Joyer", room_owner="Joyer"
        )
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Joyer",
            text="房间有哪些人",
            params="",
            raw="souler[Joyer]说：房间有哪些人@Joyer",
        )

    def test_keyword_mention_owner_at_end_with_space_separated_content(self):
        """@owner at end with space-separated preceding text."""
        result = classify_chat_line(
            "souler[Alice]说：帮我查下 @Chainer", room_owner="Chainer"
        )
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="帮我查下",
            params="",
            raw="souler[Alice]说：帮我查下 @Chainer",
        )

    def test_keyword_mention_wo_at_end_with_preceding_content(self):
        """@我 at end with preceding text (no room_owner set)."""
        result = classify_chat_line("souler[Alice]说：播放晴天@我")
        assert result == ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname="Alice",
            text="播放晴天",
            params="",
            raw="souler[Alice]说：播放晴天@我",
        )

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
