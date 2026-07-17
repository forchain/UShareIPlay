"""Chat Intake — pure classification/normalization boundary for raw chat text.

This module is side-effect-free and singleton-free. It owns the regex families
that recognize user-enter/return notifications, keyword mentions (@我), chat-room
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
_KEYWORD_PATTERN = re.compile(r"souler\[(.+?)\]说[:：]\s*@我\s+(.+)")
_ENTER_RETURN_PATTERN = re.compile(r"^(.+?)(?:进来陪你聊天啦|坐着.+来啦).*?$")


class ChatIntakeKind(Enum):
    """Taxonomy of a single raw chat line or queue part."""

    USER_ENTER = "user_enter"
    USER_RETURN = "user_return"
    KEYWORD_MENTION = "keyword_mention"
    COMMAND = "command"
    PLAIN_CHAT = "plain_chat"


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


def classify_chat_line(raw: str) -> ChatIntakeResult:
    """Classify a single raw chat line.

    Order of precedence: user enter/return, keyword mention, command, plain chat.
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

    keyword_match = _KEYWORD_PATTERN.match(raw)
    if keyword_match:
        nickname = keyword_match.group(1).strip()
        keyword_text = keyword_match.group(2).strip()
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
