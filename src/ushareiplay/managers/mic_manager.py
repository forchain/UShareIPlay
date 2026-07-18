from ushareiplay.core.singleton import Singleton


class MicManager(Singleton):
    """
    麦克风管理器 - 管理麦克风的开关状态
    单例模式，提供统一的麦克风管理服务
    """
    
    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ushareiplay.handlers.soul_handler import SoulHandler
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
        result = self.soul_handler.ui_actions.toggle_mic(enable)
        if result == {'error': 'Failed to switch to app'}:
            return {'error': 'Failed to switch to Soul app'}
        return result
    
    def get_mic_status(self) -> dict:
        """
        获取麦克风当前状态
        Returns:
            dict: 麦克风状态信息
        """
        try:
            if not self.soul_handler.key_actions.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            
            # 查找麦克风按钮
            mic_button = self.soul_handler.element_finder.try_find_element('toggle_mic')
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
