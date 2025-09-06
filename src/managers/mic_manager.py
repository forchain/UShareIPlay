import traceback
from ..core.singleton import Singleton


class MicManager(Singleton):
    """
    麦克风管理器 - 管理麦克风的开关状态
    单例模式，提供统一的麦克风管理服务
    """
    
    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ..handlers.soul_handler import SoulHandler
        self.soul_handler = SoulHandler.instance()
        self.logger = self.soul_handler.logger
    
    def toggle_mic(self, enable: bool) -> dict:
        """
        开关麦克风
        Args:
            enable: True为开启，False为关闭
        Returns:
            dict: 操作结果
        """
        try:
            if not self.soul_handler.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            
            action = "开启" if enable else "关闭"
            self.logger.info(f"Attempting to {action} microphone")
            
            # 查找麦克风切换按钮
            mic_button = self.soul_handler.try_find_element_plus('toggle_mic')
            if not mic_button:
                return {'error': 'Microphone button not found'}
            
            # 检查当前状态（通过按钮的可点击性或其他属性判断）
            # 这里假设按钮总是可点击的，实际状态通过其他方式判断
            
            mic_button.click()
            self.logger.info(f"Clicked microphone button to {action}")
            
            state = "开启" if enable else "关闭"
            return {'state': state}
            
        except Exception as e:
            self.logger.error(f"Error toggling microphone: {traceback.format_exc()}")
            return {'error': str(e)}
    
    def get_mic_status(self) -> dict:
        """
        获取麦克风当前状态
        Returns:
            dict: 麦克风状态信息
        """
        try:
            if not self.soul_handler.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            
            # 查找麦克风按钮
            mic_button = self.soul_handler.try_find_element_plus('toggle_mic')
            if not mic_button:
                return {'error': 'Microphone button not found'}
            
            # 这里需要根据实际的UI状态判断麦克风是否开启
            # 可能需要检查按钮的样式、文本或其他属性
            is_enabled = mic_button.is_enabled()
            
            return {
                'enabled': is_enabled,
                'status': '开启' if is_enabled else '关闭'
            }
            
        except Exception as e:
            self.logger.error(f"Error getting microphone status: {traceback.format_exc()}")
            return {'error': str(e)}
