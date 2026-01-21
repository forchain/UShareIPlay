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

    def reset_party_time(self):
        """Reset party creation time to current time"""
        current_time = datetime.now()
        self.init_time = current_time
        self.logger.info(f"Party creation time reset to: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")

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
            # if current_hour < 12:
            #     return

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
                    self.reset_party_time()
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
            # 从 InfoManager 获取在线人数
            from .info_manager import InfoManager
            info_manager = InfoManager.instance()
            user_count = info_manager.user_count

            if user_count is None:
                return -1
            return user_count

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

    def join_party(self) -> bool:
        """
        处理其他可能的异常情况
        返回True表示执行了操作，False表示没有找到需要处理的情况
        """

        # 检测是否在首页（非派对页面）
        try:
            planet_tab = self.handler.try_find_element_plus('planet_tab', log=False)
            if not planet_tab:
                return False
            self.logger.info("发现首页，尝试进入派对")
            planet_tab.click()

            party_hall_entry = self.handler.wait_for_element_clickable_plus('party_hall_entry')
            if not party_hall_entry:
                self.logger.warning("未找到派对大厅入口")
                return False
            party_hall_entry.click()
            self.logger.info("Clicked party hall entry")

            key, element = self.handler.wait_for_any_element_plus(
                ['party_back', 'search_entry'])
            if not element:
                self.logger.warning("未找到派对入口")
                return False

            if key == 'party_back':
                element.click()
                self.logger.info("Clicked back to party")
                return True

            if key == 'search_entry':
                search_entry = element
                search_entry.click()
                self.logger.info("Clicked search entry")
                search_box = self.handler.wait_for_element_plus('search_box')
                if not search_box:
                    self.logger.warning("未找到搜索框")
                    return False
                party_id = self.handler.party_id or self.handler.config['default_party_id']
                search_box.send_keys(party_id)
                self.logger.info(f"Entered party ID: {party_id}")
                search_button = self.handler.wait_for_element_plus('search_button')
                if not search_button:
                    self.logger.warning("未找到搜索按钮")
                    return False
                search_button.click()
                self.logger.info("Clicked search button")

                room_card = self.handler.wait_for_element_plus('room_card')
                if not room_card:
                    self.logger.warning("未找到派对房间")
                    return False
                party_online = self.handler.try_find_element_plus('party_online')
                if party_online:
                    party_online.click()
                    self.logger.info("Clicked party online")
                    return True
                else:
                    self.logger.warning("派对关闭了")
                    search_back = self.handler.wait_for_element_plus('search_back')
                    search_back.click()
                    self.logger.info("Clicked search back")

            key, element = self.handler.wait_for_any_element_plus(
                ['create_party_entry', 'create_room_entry'])
            if not element:
                self.logger.warning("未找到派对入口")
                return False
            element.click()
            self.logger.info("Clicked create party entry")

            key, element = self.handler.wait_for_any_element_plus(
                ['confirm_party', 'new_party_entry', 'party_state_entry'])
            if not element:
                self.logger.warning("未找到派对创建或恢复按钮")

            party_state_entry = None
            if key == 'new_party_entry' or key == 'confirm_party':
                element.click()
                self.logger.info(f"Clicked new party entry: {key}")
                party_state_entry = self.handler.wait_for_element_plus('party_state_entry')
            elif key == 'party_state_entry':
                party_state_entry = element

            if not party_state_entry:
                self.logger.warning("未找到创建派对屏幕")
                return False

            party_state_entry.click()
            close_party_notification = self.handler.wait_for_element_plus('close_party_notification')
            if not close_party_notification:
                self.logger.warning("未找到关闭派对推荐")
                return False
            close_party_notification.click()

            if key == 'create_party_button':
                element.click()
                self.logger.info("Clicked create party button")

                # 派对创建成功后，重置派对时间
                self.party_manager.reset_party_time()

                # 派对创建成功后，设置默认notice
                self.logger.info("派对创建成功，准备设置默认notice")
                if self._set_default_notice():
                    self.logger.info("默认notice设置成功")
                else:
                    self.logger.warning("默认notice设置失败")

                # Seat the owner after party creation
                self._seat_owner_after_party_creation()

                return True

            if key == 'confirm_party':
                element.click()
                self.logger.info("Clicked confirm party button")
                key, element = self.handler.wait_for_any_element_plus(['create_party_button', 'room_id'])
                if not element:
                    self.logger.warning("未找到派对创建或恢复按钮")
                    return False
                if key == 'create_party_button':
                    element.click()
                    self.logger.info("Clicked create party button")

                    # 派对创建成功后，重置派对时间
                    self.party_manager.reset_party_time()

                    # 派对创建成功后，设置默认notice
                    self.logger.info("派对创建成功，准备设置默认notice")
                    if self._set_default_notice():
                        self.logger.info("默认notice设置成功")
                    else:
                        self.logger.warning("默认notice设置失败")

                    # Seat the owner after party creation
                    self._seat_owner_after_party_creation()

                return True

            element.click()
            self.logger.info("Clicked restore party button")
            key, element = self.handler.wait_for_any_element_plus(['confirm_party', 'room_id'])
            if key == 'confirm_party':
                # confirm_party is found but not clickable - wait for it to become clickable
                confirm_party = self.handler.wait_for_element_clickable_plus('confirm_party')
                if not confirm_party:
                    self.logger.error("confirm party button not found")
                    return False
                confirm_party.click()
                self.logger.info("Clicked confirm party button")
                key, element = self.handler.wait_for_any_element_plus(['create_party_button', 'room_id'])
                if not element:
                    self.logger.warning("未找到派对创建或恢复按钮")
                    return False
                if key == 'create_party_button':
                    element.click()
                    self.logger.info("Clicked create party button")

            # 派对创建成功后，重置派对时间
            self.party_manager.reset_party_time()

            # 派对创建成功后，设置默认notice
            self.logger.info("派对创建成功，准备设置默认notice")
            if self._set_default_notice():
                self.logger.info("默认notice设置成功")
            else:
                self.logger.warning("默认notice设置失败")

            # Seat the owner after party creation
            self._seat_owner_after_party_creation()

            # 执行 radio 命令
            self._execute_radio_after_creation()

            return True


        except Exception as e:
            self.logger.debug(f"检测首页时出错: {str(e)}")

        return False
