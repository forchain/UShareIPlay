import pytest

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    ChatIntakeResult,
    classify_banner_line,
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

    def test_user_return_with_follower_banner_wording(self):
        result = classify_chat_line("你关注的Chainer进入房间啦，打个招呼吧～")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Chainer"
        assert result.text == "Chainer"

    def test_user_return_with_relation_brother_wording(self):
        result = classify_chat_line("你的兄弟 Outlier进来啦～")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Outlier"

    def test_user_return_with_relation_close_friend_wording(self):
        result = classify_chat_line("你的密友Chainer正在房间里，打个招呼吧～")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Chainer"

    def test_user_return_with_relation_brackets_wording(self):
        result = classify_chat_line("[Joyer]的兄弟[Outlier]进来了.[Chainer]的知己[Outlier]进来了.")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Outlier"

    def test_user_return_with_reminder_suffix(self):
        result = classify_chat_line("Outlier进来陪你聊天啦 来自派对提醒")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "Outlier"

    def test_user_return_with_generic_enter(self):
        result = classify_chat_line("张三进入房间啦")
        assert result.kind == ChatIntakeKind.USER_RETURN
        assert result.nickname == "张三"

        result2 = classify_chat_line("李四进来了")
        assert result2.kind == ChatIntakeKind.USER_RETURN
        assert result2.nickname == "李四"

    def test_user_return_excludes_system_prompts(self):
        result = classify_chat_line("进来好久了，邀请我上麦吧")
        assert result.kind == ChatIntakeKind.PLAIN_CHAT

        result2 = classify_chat_line("进入Soul星游乐场>>")
        assert result2.kind == ChatIntakeKind.PLAIN_CHAT

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


class TestMessageSourceFormatting:
    def test_format_ai_message_adds_prefix(self):
        from ushareiplay.core.chat_intake import format_ai_message

        assert format_ai_message("你好呀") == "[智能] 你好呀"

    def test_format_ai_message_preserves_existing_prefix(self):
        from ushareiplay.core.chat_intake import format_ai_message

        assert format_ai_message("[智能] 你好呀") == "[智能] 你好呀"
        assert format_ai_message("【智能】你好呀") == "【智能】你好呀"
        assert format_ai_message("[人工] 你好呀") == "[人工] 你好呀"
        assert format_ai_message("【人工】你好呀") == "【人工】你好呀"

    def test_format_ai_message_empty(self):
        from ushareiplay.core.chat_intake import format_ai_message

        assert format_ai_message("") == ""
        assert format_ai_message(None) == ""

    def test_format_manual_message_adds_prefix(self):
        from ushareiplay.core.chat_intake import format_manual_message

        assert format_manual_message("大家好") == "[人工] 大家好"

    def test_format_manual_message_preserves_existing_prefix(self):
        from ushareiplay.core.chat_intake import format_manual_message

        assert format_manual_message("[人工] 大家好") == "[人工] 大家好"
        assert format_manual_message("【人工】大家好") == "【人工】大家好"
        assert format_manual_message("[智能] 大家好") == "[智能] 大家好"
        assert format_manual_message("【智能】大家好") == "【智能】大家好"

    def test_format_manual_message_empty(self):
        from ushareiplay.core.chat_intake import format_manual_message

        assert format_manual_message("") == ""
        assert format_manual_message(None) == ""

    def test_is_manual_operator(self):
        from ushareiplay.core.chat_intake import is_manual_operator

        assert is_manual_operator("Console") is True
        assert is_manual_operator("Alice", source="console") is True
        assert is_manual_operator("Alice", source="agent_spool") is True
        assert is_manual_operator("Alice", source="chat") is False
        assert is_manual_operator("Bob") is False
        assert is_manual_operator(None) is False


class TestClassifyQuotedMessage:
    def test_quote_is_extracted_and_stripped_from_the_sender_text(self):
        result = classify_chat_line("souler[Bob]说：「Alice：今天天气不错」 哈哈")

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.nickname == "Bob"
        assert result.text == "哈哈"
        assert result.quoted_text == "Alice：今天天气不错"
        assert result.raw == "souler[Bob]说：「Alice：今天天气不错」 哈哈"

    def test_message_without_quote_has_no_quoted_text(self):
        result = classify_chat_line("souler[Bob]说：哈哈")

        assert result.quoted_text == ""

    def test_brackets_in_the_senders_own_text_are_left_alone(self):
        result = classify_chat_line("souler[Bob]说：我发了个「笑脸」 哈哈")

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == "我发了个「笑脸」 哈哈"
        assert result.quoted_text == ""
        assert result.utterance == "我发了个「笑脸」 哈哈"

    def test_quote_only_message_has_empty_text(self):
        result = classify_chat_line("souler[Bob]说：「Alice：今天天气不错」")

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == ""
        assert result.quoted_text == "Alice：今天天气不错"

    def test_command_inside_a_quote_does_not_execute(self):
        result = classify_chat_line("souler[Bob]说：「Alice：:play 晴天」 哈哈哈")

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == "哈哈哈"
        assert result.quoted_text == "Alice：:play 晴天"

    def test_mention_inside_a_quote_does_not_dispatch(self):
        result = classify_chat_line(
            "souler[Bob]说：「Alice：@群主 点歌」 哈哈哈", room_owner="群主"
        )

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == "哈哈哈"
        assert result.quoted_text == "Alice：@群主 点歌"

    def test_gift_inside_a_quote_is_not_a_gift(self):
        result = classify_chat_line(
            "souler[Bob]说：「Alice：souler[Carol]送给 Joyer 【为你爆灯】」 谢谢",
            room_owner="Joyer",
        )

        assert result.kind == ChatIntakeKind.PLAIN_CHAT
        assert result.text == "谢谢"

    def test_enter_notification_inside_a_quote_is_not_a_return(self):
        result = classify_chat_line("souler[Bob]说：「Alice：Chainer进入房间啦」 欢迎")

        assert result.kind == ChatIntakeKind.PLAIN_CHAT

    def test_sender_command_after_a_quote_still_executes(self):
        result = classify_chat_line("souler[Bob]说：「Alice：哈哈」 :play 晴天")

        assert result.kind == ChatIntakeKind.COMMAND
        assert result.nickname == "Bob"
        assert result.text == ":play 晴天"
        assert result.trigger == ":"
        assert result.quoted_text == "Alice：哈哈"

    def test_sender_mention_after_a_quote_still_dispatches(self):
        result = classify_chat_line(
            "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天", room_owner="群主"
        )

        assert result.kind == ChatIntakeKind.KEYWORD_MENTION
        assert result.nickname == "Bob"
        assert result.text == "点歌"
        assert result.params == "晴天"
        assert result.quoted_text == "Alice：哈哈"

    def test_utterance_carries_the_quote_context(self):
        result = classify_chat_line(
            "souler[Bob]说：「Alice：哈哈」 @群主 点歌 晴天", room_owner="群主"
        )

        assert result.utterance == "「Alice：哈哈」 点歌 晴天"

    def test_utterance_without_quote_is_the_plain_utterance(self):
        result = classify_chat_line("souler[Bob]说：@我 点歌 晴天")

        assert result.utterance == "点歌 晴天"

    def test_utterance_of_plain_chat(self):
        result = classify_chat_line("souler[Bob]说：「Alice：哈哈」 哈")

        assert result.utterance == "「Alice：哈哈」 哈"


class TestFormatQuotedMessage:
    def test_wrapped_sender_line_keeps_its_wrapper(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert (
            format_quoted_message("souler[Bob]说：哈哈", "Alice：今天天气不错")
            == "souler[Bob]说：「Alice：今天天气不错」 哈哈"
        )

    def test_sender_line_separator_is_preserved(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert (
            format_quoted_message("souler[Bob]说:哈哈", "Alice：好")
            == "souler[Bob]说:「Alice：好」 哈哈"
        )

    def test_unadorned_sender_line_is_prefixed_with_the_quote(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert format_quoted_message("哈哈", "Alice：好") == "「Alice：好」 哈哈"

    def test_empty_quote_returns_the_sender_line_unchanged(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert format_quoted_message("souler[Bob]说：哈哈", "") == "souler[Bob]说：哈哈"
        assert format_quoted_message("souler[Bob]说：哈哈", "   ") == "souler[Bob]说：哈哈"

    def test_empty_sender_body_has_no_trailing_space(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert format_quoted_message("souler[Bob]说：", "Alice：好") == "souler[Bob]说：「Alice：好」"

    def test_brackets_inside_the_quote_are_stripped(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert (
            format_quoted_message("souler[Bob]说：哈哈", "Alice：「嵌套」")
            == "souler[Bob]说：「Alice：嵌套」 哈哈"
        )

    def test_quote_whitespace_is_collapsed(self):
        from ushareiplay.core.chat_intake import format_quoted_message

        assert (
            format_quoted_message("souler[Bob]说：哈哈", "Alice：\n今天   天气")
            == "souler[Bob]说：「Alice： 今天 天气」 哈哈"
        )

    def test_composed_message_round_trips_through_stripping(self):
        from ushareiplay.core.chat_intake import (
            format_quoted_message,
            strip_quoted_segment,
        )

        for content in ("souler[Bob]说：哈哈", "souler[Bob]说:哈哈", "souler[Bob]说："):
            composed = format_quoted_message(content, "Alice：今天天气不错")
            assert strip_quoted_segment(composed) == content


class TestSplitQuotedMessage:
    def test_line_without_quote_is_returned_unchanged(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("souler[Bob]说：哈哈") == ("souler[Bob]说：哈哈", "")
        assert split_quoted_message("souler[Bob]说：hello  world") == (
            "souler[Bob]说：hello  world",
            "",
        )
        assert split_quoted_message("") == ("", "")

    def test_quote_after_the_wrapper_is_split_off_with_its_space(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("souler[Bob]说：「Alice：今天天气不错」 哈哈") == (
            "souler[Bob]说：哈哈",
            "Alice：今天天气不错",
        )

    def test_quote_only_line_leaves_the_wrapper(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("souler[Bob]说：「Alice：好」") == (
            "souler[Bob]说：",
            "Alice：好",
        )

    def test_unadorned_quote_is_split_off_too(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("「Alice：好」 哈哈") == ("哈哈", "Alice：好")

    def test_brackets_in_the_senders_own_body_are_not_a_quote(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("souler[Bob]说：我发了个「笑脸」 哈哈") == (
            "souler[Bob]说：我发了个「笑脸」 哈哈",
            "",
        )

    def test_only_the_leading_segment_is_the_quote(self):
        from ushareiplay.core.chat_intake import split_quoted_message

        assert split_quoted_message("souler[Bob]说：「Alice：好」 他还说「Bob：坏」") == (
            "souler[Bob]说：他还说「Bob：坏」",
            "Alice：好",
        )

    def test_strip_quoted_segment_returns_the_senders_own_line(self):
        from ushareiplay.core.chat_intake import strip_quoted_segment

        assert (
            strip_quoted_segment("souler[Bob]说：「Alice：今天天气不错」 哈哈")
            == "souler[Bob]说：哈哈"
        )
        assert strip_quoted_segment("souler[Bob]说：哈哈") == "souler[Bob]说：哈哈"


class TestClassifyBannerLine:
    """关注者横幅（follower_message 元素）的文案分类。

    这张表原先住在 FollowerMessageEvent._parse_message 里，是同一套 enter/return
    文法的第二份副本；现在横幅与聊天行走同一个入口。
    """

    @pytest.mark.parametrize(
        "banner_text, expected_nickname, expected_kind",
        [
            # 基础进入房间消息
            ("你关注的Outlier进入房间啦，打个招呼吧～", "Outlier", ChatIntakeKind.USER_RETURN),
            ("你的兄弟 Outlier进来啦～", "Outlier", ChatIntakeKind.USER_RETURN),
            # 用户日志中出现的 Warning 消息格式
            ("你的兄弟 Outlier正在房间玩～", "Outlier", ChatIntakeKind.USER_RETURN),
            ("你的密友Chainer正在房间里，打个招呼吧～", "Chainer", ChatIntakeKind.USER_RETURN),
            # 扩展场景：带空格/无空格、各种关系与动作
            ("你的死党 张三 正在房间里，打个招呼吧～", "张三", ChatIntakeKind.USER_RETURN),
            ("你的特别关注李四 正在房间里", "李四", ChatIntakeKind.USER_RETURN),
            ("你的好友 王五 进来啦～", "王五", ChatIntakeKind.USER_RETURN),
            ("你的挚友小红进入房间啦", "小红", ChatIntakeKind.USER_RETURN),
            ("你的神秘嘉宾 Alex 来到了房间", "Alex", ChatIntakeKind.USER_RETURN),
            # 点赞消息：记人不打招呼
            ("荒草 为派对点赞了", "荒草", ChatIntakeKind.PARTY_LIKE),
            ("荒草为派对点赞了", "荒草", ChatIntakeKind.PARTY_LIKE),
            # 无法解析的非法格式
            ("系统公告：欢迎使用派对功能", "", ChatIntakeKind.PLAIN_CHAT),
            ("", "", ChatIntakeKind.PLAIN_CHAT),
        ],
    )
    def test_classify_banner_line(self, banner_text, expected_nickname, expected_kind):
        result = classify_banner_line(banner_text)
        assert result.kind == expected_kind
        assert result.nickname == expected_nickname

    def test_party_like_is_not_reported_as_an_entrance(self):
        """点赞横幅不得被当成进入房间 —— 否则会替点赞的人打招呼。"""
        result = classify_banner_line("荒草 为派对点赞了")
        assert result.kind != ChatIntakeKind.USER_RETURN

    def test_enter_banner_carries_the_entrant_as_the_text(self):
        result = classify_banner_line("你关注的Outlier进入房间啦，打个招呼吧～")
        assert result.text == "Outlier"
        assert result.raw == "你关注的Outlier进入房间啦，打个招呼吧～"
