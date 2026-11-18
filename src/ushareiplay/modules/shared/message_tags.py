"""消息来源标签：`[智能]` / `[人工]` 前缀的唯一实现。

纯格式化，聊天接入（Chat Intake）与 LLM 出站适配器共用，避免任一方
因为另一方的所在层而反向依赖。
"""

KNOWN_SOURCE_TAG_PREFIXES = ("[智能]", "【智能】", "[人工]", "【人工】")


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
