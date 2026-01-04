"""
在线人数事件 - 监控在线人数变化

当检测到在线人数变化时，更新 InfoManager 中的在线人数。
"""

import re

from ..core.base_event import BaseEvent


class UserCountEvent(BaseEvent):
    """在线人数事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理在线人数事件
        
        解析人数文本并更新到 InfoManager
        
        Args:
            key: 触发事件的元素 key，这里是 'user_count'
            element_wrapper: ElementWrapper 实例，包装了在线人数元素
            
        Returns:
            bool: 默认返回 False，不中断后续处理
        """
        try:
            # 获取元素文本
            user_count_text = element_wrapper.text
            if not user_count_text:
                return False

            # 解析人数文本，例如 "6人" -> 6
            user_count = None
            if '人' in user_count_text:
                count_str = user_count_text.replace('人', '').strip()
                try:
                    user_count = int(count_str)
                except ValueError:
                    self.logger.warning(f"无法解析人数文本: {user_count_text}")
                    return False
            else:
                # 尝试提取所有数字
                match = re.search(r'(\d+)', user_count_text)
                if match:
                    try:
                        user_count = int(match.group(1))
                    except ValueError:
                        self.logger.warning(f"无法解析人数文本: {user_count_text}")
                        return False
                else:
                    self.logger.warning(f"人数文本格式异常: {user_count_text}")
                    return False

            # 更新 InfoManager 中的在线人数
            from ..managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            info_manager.user_count = user_count

            return False

        except Exception as e:
            self.logger.error(f"Error processing user count event: {str(e)}")
            return False
