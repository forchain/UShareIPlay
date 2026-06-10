from dataclasses import dataclass


@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    silent: bool = False
    private_reply: bool = False
    sleep_exempt: bool = False
