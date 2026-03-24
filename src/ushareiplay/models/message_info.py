from dataclasses import dataclass


@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str

