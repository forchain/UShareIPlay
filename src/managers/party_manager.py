import traceback
from datetime import datetime

from ..core.singleton import Singleton


class PartyManager(Singleton):
    """派对管理器，负责派对的创建、重启、监控和状态管理"""

    def __init__(self):
        # 延迟初始化，避免循环依赖
        self._handler = None
        self._logger = None
        self._recovery_manager = None

        # 派对重启相关状态
        self.init_time = None  # 初始化时间
        self.last_auto_end_date = None  # 上次自动结束日期
        self.trigger_minutes = 720  # 触发重启的时间（分钟）

    @property
    def handler(self):
        """延迟获取 Handler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def recovery_manager(self):
        """延迟获取 RecoveryManager 实例"""
        if self._recovery_manager is None:
            from .recovery_manager import RecoveryManager
            self._recovery_manager = RecoveryManager.instance()
        return self._recovery_manager

    def initialize(self):
        """初始化派对管理器"""
        if self.init_time is None:
            self.init_time = datetime.now()
            # 从配置中读取重启触发时间
            self.trigger_minutes = self.handler.config.get('party_restart_minutes', 720)
            self.logger.info(f"派对管理器已初始化，触发时间: {self.trigger_minutes}分钟")

    def update(self):
        """检查并自动管理派对"""
        try:
            # 确保已初始化
            if self.init_time is None:
                self.initialize()
                return

            current_time = datetime.now()
            current_date = current_time.date()
            current_hour = current_time.hour

            # Check if we already auto-ended today
            if self.last_auto_end_date == current_date:
                return

            # Only auto manage if current hour is between 12 and 24 (noon to midnight)
            if current_hour < 12:
                return

            # 检查是否达到触发时间（分钟）
            minutes_since_init = (current_time - self.init_time).total_seconds() / 60
            if minutes_since_init < self.trigger_minutes:
                return

            # 获取派对人数
            user_count = self.get_party_user_count()
            if user_count == -1:
                return

            # 如果只有1个人（群主），则重启派对
            if user_count == 1:
                self.logger.info("检测到只有1人在派对中，准备重启派对...")
                self.logger.info(f"运行时间: {minutes_since_init:.1f}分钟, 当前时间: {current_hour}点")

                # 关闭派对
                end_success = self.end_party()
                if end_success:
                    self.logger.info("派对关闭成功")
                    # 重置初始化时间，重新开始计时
                    self.init_time = current_time
                    self.logger.info("已重置重启功能状态，重新开始计时")
                else:
                    self.logger.error("派对关闭失败")

        except Exception as e:
            self.logger.error(f"Error in party management update: {traceback.format_exc()}")

    def end_party(self) -> dict:
        """
        结束派对（供命令调用）
        返回包含结果的字典
        """
        try:
            self.handler.send_message('Ending party')

            # Switch to Soul app first
            if not self.handler.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            self.logger.info("Switched to Soul app")

            # Click more menu
            more_menu = self.handler.wait_for_element_clickable_plus('more_menu')
            if not more_menu:
                return {'error': 'Failed to find more menu'}
            more_menu.click()
            self.logger.info("Clicked more menu")

            # Click end party option
            end_party = self.handler.wait_for_element_clickable_plus('end_party')
            if not end_party:
                return {'error': 'Failed to find end party option'}
            end_party.click()
            self.logger.info("Clicked end party option")

            # Click confirm end
            confirm_end = self.handler.wait_for_element_clickable_plus('confirm_end')
            if not confirm_end:
                return {'error': 'Failed to find confirm end button'}
            confirm_end.click()
            self.logger.info("Clicked confirm end button")

            return {'success': 'Party ended'}
        except Exception as e:
            self.logger.error(f"Error processing end command: {traceback.format_exc()}")
            return {'error': 'Failed to end party'}

    def get_party_user_count(self) -> int:
        """
        获取当前派对人数
        返回人数，如果获取失败返回-1
        """
        try:
            user_count_elem = self.handler.try_find_element_plus('user_count', log=False)
            if not user_count_elem:
                return -1

            user_count_text = user_count_elem.text
            # 解析人数文本，例如 "5人" -> 5
            if '人' in user_count_text:
                count_str = user_count_text.replace('人', '').strip()
                try:
                    return int(count_str)
                except ValueError:
                    self.logger.warning(f"无法解析人数文本: {user_count_text}")
                    return -1
            else:
                self.logger.warning(f"人数文本格式异常: {user_count_text}")
                return -1

        except Exception as e:
            self.logger.error(f"获取派对人数时出错: {traceback.format_exc()}")
            return -1

    def is_party_active(self) -> bool:
        """
        检查派对是否处于活跃状态
        返回True表示派对活跃，False表示派对不活跃
        """
        try:
            # 检查是否在派对页面
            user_count = self.get_party_user_count()
            return user_count > 0
        except Exception as e:
            self.logger.error(f"检查派对状态时出错: {traceback.format_exc()}")
            return False
