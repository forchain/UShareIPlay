import asyncio
import threading
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any, List
from ..core.singleton import Singleton


class MessageQueue(Singleton):
    """
    消息队列管理器（协程版本）
    用于 timer 和 controller 之间的消息传递
    """
    
    def __init__(self):
        self._queue = asyncio.Queue()
    
    async def put_message(self, message_info):
        """
        向队列添加消息
        Args:
            message_info: MessageInfo 对象
        """
        await self._queue.put(message_info)
    
    async def get_all_messages(self) -> Dict[str, Any]:
        """
        获取队列中的所有消息并清空队列
        Returns:
            Dict[str, MessageInfo]: 消息字典 {msg_id: MessageInfo}
        """
        messages = []
        while not self._queue.empty():
            try:
                message = self._queue.get_nowait()
                messages.append(message)
            except asyncio.QueueEmpty:
                break
        
        # Convert list to dict format expected by command manager
        result = {}
        for i, message_info in enumerate(messages):
            result[f"queue_msg_{i}"] = message_info
        
        return result
    
    def get_queue_size(self) -> int:
        """获取队列大小"""
        return self._queue.qsize()
    
    async def clear_queue(self):
        """清空队列"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
