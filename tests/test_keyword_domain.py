"""关键字领域纯规则：模式归一、命令挑选、占位符与 ACL。"""

from ushareiplay.modules.command.domain import (
    KEYWORD_MODE_RANDOM,
    KEYWORD_MODE_SEQUENCE,
    Keyword,
    normalize_keyword_mode,
    pick_keyword_command,
    render_keyword_command,
)


def test_normalize_keyword_mode_aliases_and_defaults():
    assert normalize_keyword_mode(None) == KEYWORD_MODE_SEQUENCE
    assert normalize_keyword_mode(" SEQUENTIAL ") == KEYWORD_MODE_SEQUENCE
    assert normalize_keyword_mode("ordered") == KEYWORD_MODE_SEQUENCE
    assert normalize_keyword_mode("Random") == KEYWORD_MODE_RANDOM
    assert normalize_keyword_mode("unknown") == KEYWORD_MODE_SEQUENCE


def test_pick_keyword_command_sequence_returns_full_text():
    assert pick_keyword_command(":a;:b", "sequence", chooser=lambda _c: ":b") == ":a;:b"


def test_pick_keyword_command_random_chooses_among_non_empty_parts():
    seen = []
    command = pick_keyword_command(
        " :a ; ; :b ", "random", chooser=lambda candidates: seen.append(candidates) or ":b"
    )
    assert command == ":b"
    assert seen == [[":a", ":b"]]


def test_pick_keyword_command_random_without_candidates_keeps_text():
    assert pick_keyword_command(" ; ", "random", chooser=lambda _c: "unused") == " ; "


def test_render_keyword_command_replaces_both_placeholders():
    assert render_keyword_command(":play {params} by {user_name}", "Alice", "晴天") == (
        ":play 晴天 by Alice"
    )
    assert render_keyword_command(":help {params}", "Alice") == ":help "


def _keyword(**overrides):
    data = dict(keyword="k", command=":help", creator_id=1, is_public=False)
    data.update(overrides)
    return Keyword(**data)


def test_keyword_acl_public_creator_and_allow_list():
    assert _keyword(is_public=True).allows(None) is True
    assert _keyword(is_public=True).allows(99) is True
    assert _keyword().allows(1) is True
    assert _keyword().allows(2) is False
    assert _keyword(allowed_user_ids=(2, 3)).allows(3) is True
    assert _keyword(allowed_user_ids=(2, 3)).allows(1) is True
    assert _keyword().allows(None) is False


def test_config_keyword_is_identified_by_missing_creator():
    assert _keyword(creator_id=None).is_config is True
    assert _keyword().is_config is False
