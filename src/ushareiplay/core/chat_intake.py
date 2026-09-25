"""Chat Intake — pure classification/normalization boundary for raw chat text.

This module is side-effect-free and singleton-free. It owns the regex families
that recognize user-enter/return notifications (in chat lines *and* in party
banners — see `classify_banner_line`), 点赞 banners, keyword mentions (@我 or
@owner, anywhere in the message body), chat-room
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

# Quoted Message delimiters. CJK corner brackets are unambiguous for human
# readers, naturally understood by LLMs, and practically absent from chat input.
QUOTE_OPEN = "「"
QUOTE_CLOSE = "」"

# Raw chat-line patterns. Compiled once; no I/O, no mutable state.
_CHAT_LINE_PATTERN = re.compile(r"souler\[(.+?)\]说[:：]\s*(.*)")
# Same as above but keeps the wrapper (including its separator character) so a
# composed Quoted Message can preserve the original line verbatim.
_CHAT_LINE_HEAD_PATTERN = re.compile(r"(souler\[.+?\]说[:：])\s*(.*)")
_COMMAND_PATTERN = re.compile(r"souler\[(.+?)\]说[:：]\s*([:：/／$＄])\s*(.+)")

# A Quoted Message is always the segment sitting directly after the wrapper
# (`souler[X]说：「...」 body`), or at the start of an unadorned line. Anchoring
# it there keeps 「」 the sender typed into their own text untouched. Nested
# brackets are not produced by the canonical formatter.
_QUOTED_HEAD_PATTERN = re.compile(r"^(?:(?P<wrapper>souler\[.+?\]说[:：])\s*)?「(?P<quote>[^「」]*)」\s*")
_BRACKET_CHARS_PATTERN = re.compile(r"[「」]")
_WHITESPACE_RUN_PATTERN = re.compile(r"\s+")

_ENTER_RETURN_PATTERN = re.compile(r"^(.+?)(?:进来陪你聊天啦|坐着.+来啦).*?$")
# 点赞横幅：「荒草 为派对点赞了」。它属于同一族房间横幅文案，因此归 Chat Intake 所有。
_PARTY_LIKE_PATTERN = re.compile(r"^(.+?)\s*为派对点赞了")
_GIFT_TYPE1_PATTERN = re.compile(r"souler\[(.+?)\]\s*送给\s*([^\s【]+)")
_GIFT_TYPE2_PATTERN = re.compile(r"恭喜\s*(.+?)\s*在此房间贡献出\s*(\d+)\s*热力值")

_ENTER_RELATIONS = r"(?:兄弟|密友|挚友|死党|闺蜜|基友|搭子|特别关注|好友|心动|同城|星人|萌友|CP|关注)"
_ENTER_ACTION = r"(?:进入房间|进来|正在房间|在房间|来到了房间)"

_ENTER_RETURN_PATTERNS = [
    # 格式1: 你关注的XXX... (包含横幅和聊天室通知)
    re.compile(r"^你关注的(.+?)" + _ENTER_ACTION + r".*?$"),
    # 格式2: [A]的兄弟[B]进来了. (多段或单段，取最后被引入的用户)
    re.compile(r"^.*\[[^\]]+\]的\S+?\[([^\]]+)\]进来了\.?.*?$"),
    # 格式3: 你的<已知关系词> XXX... (无论是否有空格)
    re.compile(r"^你的" + _ENTER_RELATIONS + r"\s*(.+?)" + _ENTER_ACTION + r".*?$"),
    # 格式4: 你的<关系词> XXX... (带空格分隔的任意关系词)
    re.compile(r"^你的\S{1,6}\s+(.+?)" + _ENTER_ACTION + r".*?$"),
    # 格式5: 坐着...来啦 / 进来陪你聊天啦
    re.compile(r"^(.+?)(?:进来陪你聊天啦|坐着.+来啦).*?$"),
    # 格式6: 通用进入: XXX进入房间啦 / XXX进来了 / XXX来到了房间
    re.compile(r"^(.+?)(?:进入房间啦|进入房间|来到了房间|进来了|进来啦).*?$"),
]

_ENTER_EXCLUDE_SUBSTRINGS = (
    "邀请我上麦吧",
    ">>",
    "为派对点赞了",
    "系统公告",
    "抽中",
    "恭喜",
    "更名为",
    "开启自助上麦",
    "创建群组",
    "活动火热进行中",
    "发射站",
    "通行证",
    "成为了管理员",
    "成为管理员",
)


def parse_enter_return_username(raw: str) -> str | None:
    """Parse entrant username from enter/return notifications in chat or banner text.

    Returns the extracted nickname on success, or None if the line does not match.
    """
    raw = (raw or "").strip()
    if not raw or raw.startswith("souler["):
        return None
    if any(k in raw for k in _ENTER_EXCLUDE_SUBSTRINGS):
        return None
    for pattern in _ENTER_RETURN_PATTERNS:
        m = pattern.match(raw)
        if m:
            name = m.group(1).strip()
            if name and not name.startswith("你的") and not name.startswith("你关注的"):
                return name
    return None


def parse_party_like_username(raw: str) -> str | None:
    """Parse the liker's nickname from a 点赞 banner, or None if it is not one."""
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _PARTY_LIKE_PATTERN.match(raw)
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


class ChatIntakeKind(Enum):
    """Taxonomy of a single raw chat line or queue part."""

    USER_ENTER = "user_enter"
    USER_RETURN = "user_return"
    PARTY_LIKE = "party_like"
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
        quoted_text: The Quoted Message the sender replied to, without its
                     `「...」` delimiters. Empty when the line carries no quote.
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
    quoted_text: str = ""

    @property
    def utterance(self) -> str:
        """The sender's own utterance, enriched with Quoted Message context.

        Command and mention matching always works on the sender's own text; this
        property is for consumers that want the full conversational context
        (chat-log persistence and Natural Language Command Resolution).
        """
        body = f"{self.text} {self.params}".strip() if self.params else (self.text or "").strip()
        if not self.quoted_text:
            return body
        return f"{QUOTE_OPEN}{self.quoted_text}{QUOTE_CLOSE} {body}".strip()


def _normalize_quote_text(quoted: str) -> str:
    """Collapse a Quoted Message snippet to one line without any brackets."""
    text = _BRACKET_CHARS_PATTERN.sub("", quoted or "")
    return _WHITESPACE_RUN_PATTERN.sub(" ", text).strip()


def split_quoted_message(line: str) -> tuple[str, str]:
    """Split a chat line into ``(sender's own line, Quoted Message text)``.

    A line without a quote is returned unchanged with an empty quote, so this is
    safe to apply to arbitrary chat lines. The canonical formatter always emits
    the quote immediately after the ``souler[...]说：`` wrapper, and that is the
    only segment treated as a quote — brackets the sender typed into their own
    text stay where they are.
    """
    line = line or ""
    match = _QUOTED_HEAD_PATTERN.match(line)
    if not match:
        return line, ""
    head = match.group("wrapper") or ""
    return f"{head}{line[match.end():]}", _normalize_quote_text(match.group("quote"))


def strip_quoted_segment(line: str) -> str:
    """Return the chat line as the sender typed it, without any Quoted Message."""
    return split_quoted_message(line)[0]


def format_quoted_message(content: str, quoted: str) -> str:
    """Compose the canonical Quoted Message representation of a chat line.

    ``souler[Sender]说：「RepliedAuthor：RepliedContent」 SenderContent`` — or,
    when the line carries no ``souler[...]`` wrapper, ``「...」 SenderContent``.
    A line without a quote is returned unchanged.
    """
    quote = _normalize_quote_text(quoted)
    content = content or ""
    if not quote:
        return content

    head_match = _CHAT_LINE_HEAD_PATTERN.match(content)
    if head_match:
        head = f"{head_match.group(1)}{QUOTE_OPEN}{quote}{QUOTE_CLOSE}"
        body = head_match.group(2).strip()
    else:
        head = f"{QUOTE_OPEN}{quote}{QUOTE_CLOSE}"
        body = content.strip()

    return f"{head} {body}" if body else head


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
        raw: The chat line to match against. Callers pass the sender's own text,
             i.e. with any Quoted Message already removed.
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

    Quoted Message content is extracted into `quoted_text` and removed from the
    line *before* any matching, so history quoted in a reply can never trigger a
    command, a keyword mention, or a gift — only what the sender typed does.
    """
    raw = raw or ""

    # Everything downstream matches against the sender's own text only.
    line, quoted_text = split_quoted_message(raw)

    # User enter/return notifications are system-style lines without the souler
    # wrapper; check them first so they are not mistaken for plain chat.
    entrant_name = parse_enter_return_username(line)
    if entrant_name:
        return ChatIntakeResult(
            kind=ChatIntakeKind.USER_RETURN,
            nickname=entrant_name,
            text=entrant_name,
            raw=raw,
            quoted_text=quoted_text,
        )

    gift1_match = _GIFT_TYPE1_PATTERN.search(line)
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
                quoted_text=quoted_text,
            )

    gift2_match = _GIFT_TYPE2_PATTERN.search(line)
    if gift2_match:
        giver = gift2_match.group(1).strip()
        heat_val = int(gift2_match.group(2))
        return ChatIntakeResult(
            kind=ChatIntakeKind.GIFT_RECEIVE,
            nickname=giver,
            text=giver,
            raw=raw,
            heat_value=heat_val,
            quoted_text=quoted_text,
        )

    if room_owner and room_owner.strip() and room_owner.strip() != "我":
        escaped_owner = re.escape(room_owner.strip())
        mention_re = rf"(?:@我|@{escaped_owner})"
    else:
        mention_re = "@我"

    keyword_result = _find_keyword_mention(line, mention_re)

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
            quoted_text=quoted_text,
        )

    command_match = _COMMAND_PATTERN.match(line)
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
            quoted_text=quoted_text,
        )

    # Not a recognized structured line. Try to strip the souler wrapper so that
    # plain chat results carry the visible text; otherwise keep the whole raw line.
    wrapper_match = _CHAT_LINE_PATTERN.match(line)
    if wrapper_match:
        nickname = wrapper_match.group(1).strip()
        text = wrapper_match.group(2)
    else:
        nickname = ""
        text = line

    return ChatIntakeResult(
        kind=ChatIntakeKind.PLAIN_CHAT,
        nickname=nickname,
        text=text,
        raw=raw,
        quoted_text=quoted_text,
    )


def classify_banner_line(raw: str) -> ChatIntakeResult:
    """Classify a Soul party *banner* line (the follower banner element).

    Banners announce room events rather than carry a speaker, so they use the
    same enter/return grammar as chat lines but need no speaker extraction and
    no command/mention interpretation:

    - ``USER_RETURN``: someone entered the room. The banner says "entered"; whether
      this counts as a *return* (vs. a fresh enter) is `PresenceTracker`'s decision,
      which is why `classify_chat_line` uses the same kind for the same text.
    - ``PARTY_LIKE``: someone liked the party (``荒草 为派对点赞了``). Recorded, not greeted.
    - ``PLAIN_CHAT`` with an empty nickname: unrecognized banner text.

    Callers that only react to entrances should test
    ``result.kind == ChatIntakeKind.USER_RETURN``; ``result.nickname`` is the person.
    """
    raw = raw or ""
    if not raw.strip():
        return ChatIntakeResult(kind=ChatIntakeKind.PLAIN_CHAT, nickname="", text="", raw=raw)

    # 点赞 first: the enter/return parser deliberately excludes 点赞 lines, but a
    # liker is still a real person worth recording.
    liker = parse_party_like_username(raw)
    if liker:
        return ChatIntakeResult(
            kind=ChatIntakeKind.PARTY_LIKE, nickname=liker, text=liker, raw=raw
        )

    entrant = parse_enter_return_username(raw)
    if entrant:
        return ChatIntakeResult(
            kind=ChatIntakeKind.USER_RETURN, nickname=entrant, text=entrant, raw=raw
        )

    return ChatIntakeResult(kind=ChatIntakeKind.PLAIN_CHAT, nickname="", text=raw, raw=raw)


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
