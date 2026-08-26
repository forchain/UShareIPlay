"""Chat Intake — pure classification/normalization boundary for raw chat text.

This module is side-effect-free and singleton-free. It owns the regex families
that recognize user-enter/return notifications, keyword mentions (@我 or @owner,
anywhere in the message body), chat-room
commands, and plain chat lines, plus the queue grammar used by timer/runtime
messages (`;` split, `{user_name}` expansion, silent/private prefix detection).

All functions return frozen `ChatIntakeResult` objects. Callers are responsible
for dispatching to KeywordManager, CommandManager, or the chat logger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


COMMAND_PREFIXES = (":", "：", "/", "／")
SILENT_COMMAND_PREFIXES = ("/", "／")
PRIVATE_REPLY_PREFIXES = ("$", "＄")
QUEUE_COMMAND_PREFIXES = COMMAND_PREFIXES + PRIVATE_REPLY_PREFIXES
QUEUE_COMMAND_PREFIX_CHARS = "".join(QUEUE_COMMAND_PREFIXES)

# Raw chat-line patterns. Compiled once; no I/O, no mutable state.
_CHAT_LINE_PATTERN = re.compile(r"souler\[(.+?)\]说[:：]\s*(.*)")
_COMMAND_PATTERN = re.compile(r"souler\[(.+?)\]说[:：]\s*([:：/／$＄])\s*(.+)")

_ENTER_RETURN_PATTERN = re.compile(r"^(.+?)(?:进来陪你聊天啦|坐着.+来啦).*?$")
_GIFT_TYPE1_PATTERN = re.compile(r"souler\[(.+?)\]\s*送给\s*([^\s【]+)")
_GIFT_TYPE2_PATTERN = re.compile(r"恭喜\s*(.+?)\s*在此房间贡献出\s*(\d+)\s*热力值")


class ChatIntakeKind(Enum):
    """Taxonomy of a single raw chat line or queue part."""

    USER_ENTER = "user_enter"
    USER_RETURN = "user_return"
    KEYWORD_MENTION = "keyword_mention"
    COMMAND = "command"
    PLAIN_CHAT = "plain_chat"
    GIFT_RECEIVE = "gift_receive"


@dataclass(frozen=True)
class ChatIntakeResult:
    """Frozen classification result for one chat line or queue part.

    Fields:
        kind: What kind of message this is.
        nickname: The speaker/user name (extracted from the line or passed in).
        text: Normalized payload. For COMMAND this includes the trigger prefix
              (e.g. ":play 123"); for KEYWORD_MENTION this is the keyword only;
              for USER_ENTER/RETURN this is the username; for PLAIN_CHAT this is
              the raw visible text.
        params: Parameters after the keyword (only set for KEYWORD_MENTION).
        trigger: The matched command trigger character (only set for COMMAND).
        silent: True if the command should suppress screen output.
        private_reply: True if the command should be answered privately.
        sleep_exempt: Inherited sleep-exemption flag (queue expansion only).
        raw: The original input string, preserved for debugging.
        heat_value: Heat value amount (only set for GIFT_RECEIVE Type 2).
    """

    kind: ChatIntakeKind
    nickname: str
    text: str
    params: str = ""
    trigger: str = ""
    silent: bool = False
    private_reply: bool = False
    sleep_exempt: bool = False
    raw: str = ""
    heat_value: int = 0



def _find_keyword_mention(
    raw: str,
    mention_re: str,
) -> tuple[str, str] | None:
    """Return (nickname, keyword_text) if *raw* contains a keyword mention, else None.

    Two matching paths are tried in order:

    1. **Content-after**: ``@mention`` appears anywhere in the message body,
       followed by mandatory whitespace and at least one character of content.
       This is the normal case (mention at start or middle).  The mandatory
       ``\\s+`` prevents false positives from粘连 forms like ``@ownerXYZ``.

    2. **Content-before**: ``@mention`` appears at the very end of the line
       (optional trailing whitespace).  The content is whatever preceded the
       mention.  At least one non-whitespace character must be present before
       the mention so a bare ``@owner`` (no surrounding text) is not matched.

    Args:
        raw: Full raw chat line.
        mention_re: Compiled regex fragment that matches the mention token
                    (e.g. ``@我`` or ``(?:@我|@Joyer)``).

    Returns:
        ``(nickname, keyword_text)`` on success, ``None`` otherwise.
        *keyword_text* is the raw content string (not yet split into
        keyword/params); callers must strip and split as needed.
    """
    # Path 1: content comes AFTER the mention (mention at start or middle)
    m = re.match(
        rf"souler\[(.+?)\]说[:：]\s*.*?{mention_re}\s+(.+)",
        raw,
    )
    if m:
        return m.group(1).strip(), m.group(2)

    # Path 2: mention is at the end; content comes BEFORE it.
    # (.+?) ensures at least one char of content before the mention.
    m = re.match(
        rf"souler\[(.+?)\]说[:：]\s*(.+?)\s*{mention_re}\s*$",
        raw,
    )
    if m:
        return m.group(1).strip(), m.group(2)

    return None


def classify_chat_line(raw: str, room_owner: str | None = None) -> ChatIntakeResult:
    """Classify a single raw chat line.

    Order of precedence: user enter/return, gift receive, keyword mention, command, plain chat.
    The result is frozen; callers may convert it to a mutable MessageInfo if needed.
    """
    raw = raw or ""

    # User enter/return notifications are system-style lines without the souler
    # wrapper; check them first so they are not mistaken for plain chat.
    enter_match = _ENTER_RETURN_PATTERN.match(raw)
    if enter_match:
        username = enter_match.group(1).strip()
        # Soul uses the same wording for "user entered" and "user returned" chat
        # lines. The existing code treats both as return events to avoid double
        # firing with InfoManager's online-user diff, which is the real source of
        # user-enter notifications. Preserve that behavior.
        return ChatIntakeResult(
            kind=ChatIntakeKind.USER_RETURN,
            nickname=username,
            text=username,
            raw=raw,
        )

    gift1_match = _GIFT_TYPE1_PATTERN.search(raw)
    if gift1_match:
        giver = gift1_match.group(1).strip()
        receiver = gift1_match.group(2).strip()
        if room_owner and receiver == room_owner.strip():
            return ChatIntakeResult(
                kind=ChatIntakeKind.GIFT_RECEIVE,
                nickname=giver,
                text=giver,
                raw=raw,
                heat_value=0,
            )

    gift2_match = _GIFT_TYPE2_PATTERN.search(raw)
    if gift2_match:
        giver = gift2_match.group(1).strip()
        heat_val = int(gift2_match.group(2))
        return ChatIntakeResult(
            kind=ChatIntakeKind.GIFT_RECEIVE,
            nickname=giver,
            text=giver,
            raw=raw,
            heat_value=heat_val,
        )

    if room_owner and room_owner.strip() and room_owner.strip() != "我":
        escaped_owner = re.escape(room_owner.strip())
        mention_re = rf"(?:@我|@{escaped_owner})"
    else:
        mention_re = "@我"

    keyword_result = _find_keyword_mention(raw, mention_re)

    if keyword_result:
        nickname, keyword_text = keyword_result
        keyword_text = keyword_text.strip()
        parts = keyword_text.split(None, 1)
        keyword = parts[0] if parts else ""
        params = parts[1] if len(parts) > 1 else ""
        return ChatIntakeResult(
            kind=ChatIntakeKind.KEYWORD_MENTION,
            nickname=nickname,
            text=keyword,
            params=params,
            raw=raw,
        )

    command_match = _COMMAND_PATTERN.match(raw)
    if command_match:
        nickname = command_match.group(1).strip()
        trigger = command_match.group(2)
        content = command_match.group(3).strip()
        text = f"{trigger}{content}" if content else ""
        return ChatIntakeResult(
            kind=ChatIntakeKind.COMMAND,
            nickname=nickname,
            text=text,
            trigger=trigger,
            silent=trigger in SILENT_COMMAND_PREFIXES,
            private_reply=trigger in PRIVATE_REPLY_PREFIXES,
            raw=raw,
        )

    # Not a recognized structured line. Try to strip the souler wrapper so that
    # plain chat results carry the visible text; otherwise keep the whole raw line.
    wrapper_match = _CHAT_LINE_PATTERN.match(raw)
    if wrapper_match:
        nickname = wrapper_match.group(1).strip()
        text = wrapper_match.group(2)
    else:
        nickname = ""
        text = raw

    return ChatIntakeResult(
        kind=ChatIntakeKind.PLAIN_CHAT,
        nickname=nickname,
        text=text,
        raw=raw,
    )


def _detect_command_prefix(text: str) -> str | None:
    """Return the matched queue-command prefix at the start of text, or None."""
    s = text.lstrip()
    if not s:
        return None
    first = s[0]
    return first if first in QUEUE_COMMAND_PREFIXES else None


def is_private_reply_prefix(text: str) -> bool:
    """Return True if text starts with a private-reply prefix."""
    s = (text or "").lstrip()
    return bool(s) and s[0] in PRIVATE_REPLY_PREFIXES


def is_silent_prefix(text: str) -> bool:
    """Return True if text starts with a silent-command prefix (after optional private-reply prefix)."""
    s = (text or "").lstrip()
    if is_private_reply_prefix(s):
        s = s[1:].lstrip()
    return bool(s) and s[0] in SILENT_COMMAND_PREFIXES


def normalize_command_text(raw: str) -> str:
    """Strip the leading command trigger and surrounding whitespace.

    Returns the cleaned command content, or an empty string if there is none.
    """
    s = (raw or "").lstrip()
    if not s:
        return ""
    if is_private_reply_prefix(s):
        s = s[1:].lstrip()
    if s and s[0] in COMMAND_PREFIXES:
        s = s[1:]
    return s.lstrip()


def expand_queue_text(
    text: str,
    nickname: str,
    *,
    silent: bool = False,
    sleep_exempt: bool = False,
) -> list[ChatIntakeResult]:
    """Expand a runtime queue message into classified parts.

    Supports the queue grammar: `;` splits parts, `{user_name}` is substituted,
    and leading `:`, `：`, `/`, `／`, `$`, `＄` classify a part as a command with
    the appropriate silent/private flags.

    Args:
        text: Raw queue message content.
        nickname: Nickname to substitute for `{user_name}`.
        silent: Inherited silent flag from the queued MessageInfo.
        sleep_exempt: Inherited sleep-exempt flag from the queued MessageInfo.

    Returns:
        A list of frozen ChatIntakeResult objects, one per non-empty part.
    """
    text = text or ""
    nickname = nickname or ""
    results: list[ChatIntakeResult] = []

    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        part = part.replace("{user_name}", nickname)

        prefix = _detect_command_prefix(part)
        if prefix is not None:
            results.append(
                ChatIntakeResult(
                    kind=ChatIntakeKind.COMMAND,
                    nickname=nickname,
                    text=part,
                    trigger=prefix,
                    silent=silent or (prefix in SILENT_COMMAND_PREFIXES),
                    private_reply=prefix in PRIVATE_REPLY_PREFIXES,
                    sleep_exempt=sleep_exempt,
                    raw=part,
                )
            )
        else:
            results.append(
                ChatIntakeResult(
                    kind=ChatIntakeKind.PLAIN_CHAT,
                    nickname=nickname,
                    text=part,
                    silent=silent,
                    sleep_exempt=sleep_exempt,
                    raw=part,
                )
            )

    return results


KNOWN_SOURCE_TAG_PREFIXES = ("[智能]", "【智能】", "[人工]", "【人工】")
MANUAL_OPERATOR_NICKNAMES = ("Console",)
MANUAL_OPERATOR_SOURCES = ("console", "agent_spool")


def is_manual_operator(nickname: str | None, source: str | None = None) -> bool:
    """Check whether a message originates from the manual backend operator."""
    if nickname in MANUAL_OPERATOR_NICKNAMES:
        return True
    if source in MANUAL_OPERATOR_SOURCES:
        return True
    return False


def _format_tagged_message(text: str, tag: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    if any(s.startswith(prefix) for prefix in KNOWN_SOURCE_TAG_PREFIXES):
        return s
    return f"{tag} {s}"


def format_ai_message(text: str) -> str:
    """Ensure AI/LLM-generated conversational output is tagged with [智能] prefix.

    Avoids duplicating prefix if already present or if another source tag exists.
    """
    return _format_tagged_message(text, "[智能]")


def format_manual_message(text: str) -> str:
    """Ensure backend console/manual output is tagged with [人工] prefix.

    Avoids duplicating prefix if already present or if another source tag exists.
    """
    return _format_tagged_message(text, "[人工]")
