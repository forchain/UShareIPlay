import time
import traceback
from typing import Dict
from datetime import datetime
from ..core.singleton import Singleton


class NoticeManager(Singleton):
    """Notice管理器，统一处理notice的设置操作"""

    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ..handlers.soul_handler import SoulHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger

        # 冷却时间管理
        self.last_update_time = None
        self.cooldown_minutes = 15  # 15分钟冷却时间
        self.pending_notice = None  # 待设置的notice

    def can_update_now(self) -> bool:
        """检查是否可以立即更新notice
        Returns:
            bool: True如果可以更新，False如果在冷却中
        """
        if not self.last_update_time:
            return True
        
        current_time = datetime.now()
        time_diff = current_time - self.last_update_time
        return time_diff.total_seconds() >= self.cooldown_minutes * 60

    def get_remaining_cooldown_minutes(self) -> int:
        """获取剩余冷却时间（分钟）
        Returns:
            int: 剩余冷却时间（分钟）
        """
        if not self.last_update_time:
            return 0
        
        current_time = datetime.now()
        time_diff = current_time - self.last_update_time
        remaining_seconds = (self.cooldown_minutes * 60) - time_diff.total_seconds()
        return max(0, int(remaining_seconds / 60))

    def set_notice_with_cooldown(self, notice: str) -> Dict:
        """带冷却时间检查的设置notice方法
        Args:
            notice: 要设置的notice内容
        Returns:
            dict: 包含成功、错误或冷却信息的结果
        """
        if not self.can_update_now():
            remaining_minutes = self.get_remaining_cooldown_minutes()
            self.pending_notice = notice
            self.logger.info(f"Notice update in cooldown, {remaining_minutes} minutes remaining. Notice will be set: {notice}")
            return {
                'cooldown': True,
                'remaining_minutes': remaining_minutes,
                'pending_notice': notice,
                'message': f'Notice will be updated in {remaining_minutes} minutes'
            }
        
        # 可以立即更新
        result = self._set_notice_immediate(notice)
        
        # 无论成功还是失败，都更新冷却时间，避免重复尝试
        self.last_update_time = datetime.now()
        
        if 'success' in result:
            self.pending_notice = None
            self.logger.info("Notice set successfully, cooldown updated")
        else:
            # 失败时也标记为待处理，等待下一个冷却周期
            self.pending_notice = notice
            self.logger.warning(f"Notice set failed, will retry in next cooldown cycle: {result.get('error', 'Unknown error')}")
        
        return result

    def _set_notice_immediate(self, notice: str) -> Dict:
        """立即设置notice（不检查冷却时间）
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
            
        except Exception:
            self.logger.error(f"设置notice时出错: {traceback.format_exc()}")
            return {'error': f'Failed to update notice to {notice}'}

    def set_notice(self, notice: str) -> Dict:
        """
        设置房间notice（保持向后兼容，使用冷却时间管理）
        Args:
            notice: 要设置的notice内容
        Returns:
            dict: 包含成功或错误信息的结果
        """
        return self.set_notice_with_cooldown(notice)

    def process_pending_notice(self) -> Dict:
        """处理待设置的notice（在冷却时间过后）
        Returns:
            dict: 处理结果
        """
        if not self.pending_notice:
            return {'skipped': 'No pending notice'}
        
        if not self.can_update_now():
            remaining_minutes = self.get_remaining_cooldown_minutes()
            return {'cooldown': True, 'remaining_minutes': remaining_minutes}
        
        # 可以设置待处理的notice
        notice = self.pending_notice
        result = self._set_notice_immediate(notice)
        
        # 无论成功还是失败，都更新冷却时间
        self.last_update_time = datetime.now()
        
        if 'success' in result:
            self.pending_notice = None
            self.logger.info(f"Successfully processed pending notice: {notice}")
        else:
            # 失败时保持待处理状态，等待下一个冷却周期
            self.logger.warning(f"Failed to process pending notice, will retry in next cooldown cycle: {result.get('error', 'Unknown error')}")
        
        return result

    def update(self):
        """定期检查并处理待设置的notice
        Returns:
            dict: 处理结果，如果没有待处理的notice则返回None
        """
        try:
            if not self.pending_notice:
                return None
            
            result = self.process_pending_notice()
            if 'success' in result:
                self.logger.info(f"Successfully processed pending notice: {result.get('success', '')}")
                return result
            elif 'cooldown' in result:
                # self.logger.debug(f"Notice still in cooldown, {remaining_minutes} minutes remaining")
                return result
            elif 'error' in result:
                self.logger.warning(f"Failed to process pending notice: {result['error']}")
                return result
            else:
                return result
                
        except Exception as e:
            self.logger.error(f"Error in notice update: {str(e)}")
            return {'error': f'Error in notice update: {str(e)}'}

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
