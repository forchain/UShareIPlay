import time
import traceback
from typing import Dict


class NoticeManager:
    """Notice管理器，统一处理notice的设置操作"""

    def __init__(self, handler):
        self.handler = handler
        self.logger = handler.logger

    def set_notice(self, notice: str) -> Dict:
        """
        设置房间notice
        Args:
            notice: 要设置的notice内容
        Returns:
            dict: 包含成功或错误信息的结果
        """
        try:
            self.logger.info(f"准备设置notice: {notice}")
            
            # 点击小助手
            assistant = self.handler.wait_for_element_clickable_plus('little_assistant')
            if not assistant:
                return {'error': 'Failed to find little assistant'}
            assistant.click()
            self.logger.info("点击了小助手按钮")
            
            # 点击编辑notice入口
            edit_entry = self.handler.wait_for_element_clickable_plus('edit_notice_entry')
            if not edit_entry:
                return {'error': 'Failed to find edit notice entry'}
            edit_entry.click()
            self.logger.info("点击了编辑notice入口")
            
            # 检查是否有关闭按钮
            close_notice = self.handler.wait_for_element_plus('close_notice')
            if not close_notice:
                return {'error': 'Close notice not found'}
                
            # 点击自定义按钮
            customize = self.handler.try_find_element_plus('customize_notice_button')
            if not customize:
                close_notice.click()
                self.logger.warning('Bottom drawer is open, notice customization is disabled, hiding...')
                return {'error': 'Failed to find customize notice button'}
            customize.click()
            self.logger.info("点击了自定义按钮")
            
            # 输入新的notice
            notice_input = self.handler.wait_for_element_clickable_plus('edit_notice_input')
            if not notice_input:
                return {'error': 'Failed to find notice input'}
            notice_input.clear()
            notice_input.send_keys(notice)
            self.logger.info(f"输入了notice内容: {notice}")
            
            # 点击确认
            confirm = self.handler.wait_for_element_clickable_plus('edit_notice_confirm')
            if not confirm:
                return {'error': 'Failed to find confirm button'}
            confirm.click()
            self.logger.info("点击了确认按钮")
            
            # 关闭notice设置对话框
            close_notice = self.handler.wait_for_element_plus('close_notice')
            if close_notice:
                self.logger.info("隐藏notice设置对话框")
                close_notice.click()
                
            self.logger.info(f"成功设置notice: {notice}")
            return {'success': True}
            
        except Exception as e:
            self.logger.error(f"设置notice时出错: {traceback.format_exc()}")
            return {'error': f'Failed to update notice to {notice}'}

    def set_default_notice(self) -> Dict:
        """
        设置默认notice（从配置中读取）
        Returns:
            dict: 包含成功或错误信息的结果
        """
        try:
            default_notice = self.handler.config.get('default_notice')
            if not default_notice:
                self.logger.warning("未找到default_notice配置")
                return {'error': 'No default_notice configuration found'}
                
            self.logger.info(f"准备设置默认notice: {default_notice}")
            
            # 等待界面稳定
            time.sleep(3)
            
            # 调用通用设置方法
            result = self.set_notice(default_notice)
            if 'success' in result:
                self.logger.info(f"成功设置默认notice: {default_notice}")
            else:
                self.logger.warning(f"设置默认notice失败: {result.get('error', 'Unknown error')}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"设置默认notice时出错: {str(e)}")
            return {'error': f'Failed to set default notice: {str(e)}'}

    def get_status_info(self) -> Dict:
        """
        获取Notice管理器的状态信息
        """
        return {
            'handler_available': self.handler is not None,
            'config_available': hasattr(self.handler, 'config') if self.handler else False,
            'default_notice': self.handler.config.get('default_notice') if self.handler and hasattr(self.handler, 'config') else None
        }
