from dataclasses import dataclass


@dataclass
class MessageInfo:
    """Data class for message information

    `intake_classified` marks a message that Chat Intake already classified
    (`classify_chat_line` → `build_message_batch`), with every flag attached.
    The runtime queue must hand such a message to execution untouched: applying
    the queue grammar to it would split on `;` and rebuild the message without
    its metadata. Producers that emit raw text (timers, console/agent input)
    leave the flag `False`, so they keep `;` splitting and `{user_name}`
    substitution.
    """

    content: str
    nickname: str
    silent: bool = False
    private_reply: bool = False
    sleep_exempt: bool = False
    source: str | None = None
    quoted_text: str = ""
    intake_classified: bool = False
