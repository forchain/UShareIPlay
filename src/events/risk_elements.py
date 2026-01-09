"""
风险元素事件 - 处理潜在风险元素

监控以下元素：
- claim_reward_button: 领取奖励按钮
- new_message_tip: 新消息提示
- close_button: 关闭按钮
- collapse_seats: 收起座位

当检测到这些元素时，自动点击处理，避免界面不稳定。
"""

__event__ = "RiskElementsEvent"
__elements__ = [
    'collapse_seats',
    'new_message_tip',
    'floating_entry',

    # conflicts with '关闭组件' in party  hall
    # 'close_button',
    'claim_reward_button',
    'party_ended',
    'confirm_close_3',
    'close_widget'
]

from ..core.base_event import BaseEvent


class RiskElementsEvent(BaseEvent):
    """风险元素事件处理器"""

    async def handle(self, key: str, element_wrapper):
        """
        处理风险元素事件
        
        找到控件并点击，使用 wait_for 因为之前已经确定控件存在了
        
        Args:
            key: 触发事件的元素 key
            element_wrapper: ElementWrapper 实例，包装了风险元素
            
        Returns:
            bool: 如果点击成功返回 True，否则 False
        """
        try:
            # 使用 wait_for 获取可点击的元素（因为 page_source 中已确认存在）
            element = self.handler.wait_for_element_clickable_plus(key)
            if not element:
                self.logger.warning(f"Risk element {key} found in page_source but not clickable")
                return False

            element.click()
            self.logger.info(f"Processed risk element: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Error processing risk element {key}: {str(e)}")
            return False

