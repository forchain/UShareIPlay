import time
import traceback
from datetime import datetime

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.models import MessageInfo
from ushareiplay.core.singleton import Singleton


class PartyManager(Singleton):
    """派对管理器，负责派对的创建、重启、监控和状态管理"""

    def __init__(self):
        # 延迟初始化，避免循环依赖
        self._handler = None
        self._logger = None
        self._message_dispatch = None

        # 派对重启相关状态
        self.init_time = None  # 初始化时间
        self.last_auto_end_date = None  # 上次自动结束日期
        self.trigger_minutes = 720  # 触发重启的时间（分钟）

    @property
    def handler(self):
        """延迟获取 Handler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.handler)
        return self._message_dispatch

    def initialize_party(self):
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
                self.initialize_party()
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
            self.message_dispatch.send_screen_message('Ending party')

            # Switch to Soul app first
            if not self.handler.key_actions.switch_to_app():
                return {'error': 'Failed to switch to Soul app'}
            self.logger.info("Switched to Soul app")

            # Try direct exit_room_btn first
            exit_room_btn = self.handler.element_finder.try_find_element('exit_room_btn', log=False)
            if exit_room_btn:
                exit_room_btn.click()
                self.logger.info("Clicked exit room button directly")
            else:
                self.logger.info("Direct exit room button not found, trying more menu...")
                # Click more menu
                more_menu = self.handler.element_finder.wait_for_element_clickable('more_menu')
                if not more_menu:
                    return {'error': 'Failed to find more menu'}
                more_menu.click()
                self.logger.info("Clicked more menu")

                # Click end party option
                end_party = self.handler.element_finder.wait_for_element_clickable('end_party')
                if not end_party:
                    return {'error': 'Failed to find end party option'}
                end_party.click()
                self.logger.info("Clicked end party option")

            # Click confirm end
            confirm_end = self.handler.element_finder.wait_for_element_clickable('confirm_end')
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
            from ushareiplay.managers.info_manager import InfoManager
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

    async def invite_user(self, message_info: MessageInfo, party_id: str) -> dict:
        """
        邀请当前账号加入指定派对（切房）
        Args:
            message_info: 消息信息（用于等级校验和返回展示）
            party_id: 派对 ID
        Returns:
            dict: 成功含 party_id、user；失败含 error、party_id
        """
        try:
            # Check if we can directly close the room (we are the host)
            exit_room_btn = self.handler.element_finder.try_find_element('exit_room_btn', log=False)
            if exit_room_btn:
                exit_room_btn.click()
                self.logger.info("Clicked exit room button directly")
                confirm_end = self.handler.element_finder.wait_for_element_clickable('confirm_end')
                if confirm_end:
                    confirm_end.click()
                self.handler.party_id = party_id
                return {'party_id': party_id, 'user': message_info.nickname}

            more_menu = self.handler.element_finder.wait_for_element_clickable('more_menu')
            if not more_menu:
                return {
                    'error': 'Failed to find more menu button',
                    'party_id': party_id
                }
            more_menu.click()
            self.logger.info("Clicked more menu button")

            self.handler.element_finder.wait_for_element('more_menu_container')

            end_party = self.handler.element_finder.try_find_element('end_party', log=False)
            if end_party:
                end_party.click()
                confirm_end = self.handler.element_finder.wait_for_element_clickable('confirm_end')
                if confirm_end:
                    confirm_end.click()
                self.handler.party_id = party_id
                return {'party_id': party_id, 'user': message_info.nickname}

            party_hall = self.handler.element_finder.wait_for_element_clickable('party_hall')
            if not party_hall:
                return {
                    'error': 'Failed to find party hall entry',
                    'party_id': party_id
                }
            party_hall.click()
            self.logger.info("Clicked party hall entry")

            search_entry = self.handler.element_finder.wait_for_element_clickable('search_entry')
            if not search_entry:
                return {
                    'error': 'Failed to find search entry',
                    'party_id': party_id
                }
            search_entry.click()
            self.logger.info("Clicked search entry")

            search_box = self.handler.element_finder.wait_for_element_clickable('search_box')
            if not search_box:
                return {
                    'error': 'Failed to find search box',
                    'party_id': party_id
                }
            search_box.send_keys(party_id)
            self.logger.info(f"Entered party ID: {party_id}")

            search_button = self.handler.element_finder.wait_for_element_clickable('search_button')
            if not search_button:
                return {
                    'error': 'Failed to find search button',
                    'party_id': party_id
                }
            search_button.click()
            self.logger.info("Clicked search button")

            parties_search = self.handler.element_finder.wait_for_element('parties_search')
            if not parties_search:
                return {
                    'error': 'Failed to find parties search',
                    'party_id': party_id
                }
            self.logger.info("Found parties search result")

            time.sleep(1)
            party_element = self.handler.element_finder.find_child_element(parties_search, 'party_id')
            if not party_element:
                self.logger.info("Party not found, returning to previous party")
                floating_entry = self.handler.element_finder.wait_for_element_clickable('floating_entry')
                if floating_entry:
                    floating_entry.click()
                return {
                    'error': f'Party {party_id} not found',
                    'party_id': party_id
                }

            party_element.click()
            self.logger.info(f"Entered party {party_id}")

            self.handler.grab_mic_and_confirm()
            return {'party_id': party_id, 'user': message_info.nickname}

        except Exception as e:
            self.logger.error(f"Error inviting to party: {traceback.format_exc()}")
            return {
                'error': str(e),
                'party_id': party_id
            }

    async def join_party(self) -> bool:
        """
        处理其他可能的异常情况
        返回True表示执行了操作，False表示没有找到需要处理的情况
        """
        try:
            if not self._enter_party_hall_from_home():
                return False

            if self._search_and_try_enter_existing_party():
                return True

            if not self._create_party_flow():
                return False
            await self._after_party_created()
            return True


        except Exception as e:
            self.logger.debug(f"检测首页时出错: {str(e)}")

        return False

    def _enter_party_hall_from_home(self) -> bool:
        planet_tab = self.handler.element_finder.try_find_element('planet_tab', log=False)
        if not planet_tab:
            return False
        self.logger.info("发现首页，尝试进入派对")
        planet_tab.click()

        party_hall_entry = self.handler.element_finder.wait_for_element_clickable('party_hall_entry')
        if not party_hall_entry:
            self.logger.warning("未找到派对大厅入口")
            return False
        party_hall_entry.click()
        self.logger.info("Clicked party hall entry")
        return True

    def _search_and_try_enter_existing_party(self) -> bool:
        key, element = self.handler.element_finder.wait_for_any_element(['party_back', 'search_entry'])
        if not element:
            self.logger.warning("未找到派对入口")
            return False

        if key == 'party_back':
            element.click()
            self.logger.info("Clicked back to party")
            return True

        search_entry = element
        search_entry.click()
        self.logger.info("Clicked search entry")
        search_box = self.handler.element_finder.wait_for_element('search_box')
        if not search_box:
            self.logger.warning("未找到搜索框")
            return False

        party_id = self.handler.party_id or self.handler.config['default_party_id']
        search_box.send_keys(party_id)
        self.logger.info(f"Entered party ID: {party_id}")
        search_button = self.handler.element_finder.wait_for_element('search_button')
        if not search_button:
            self.logger.warning("未找到搜索按钮")
            return False
        search_button.click()
        self.logger.info("Clicked search button")

        room_card = self.handler.element_finder.wait_for_element('room_card')
        if not room_card:
            self.logger.warning("未找到派对房间，视为派对关闭，准备重建派对")
            self._go_back_from_search()
            return False

        party_online = self.handler.element_finder.try_find_element('party_online')
        if party_online:
            party_online.click()
            self.logger.info("Clicked party online")
            return True

        self.logger.warning("派对关闭了")
        self._go_back_from_search()
        return False

    def _go_back_from_search(self) -> None:
        search_back = self.handler.element_finder.wait_for_element('search_back')
        if search_back:
            search_back.click()
            self.logger.info("Clicked search back")
            return
        self.logger.warning("未找到搜索返回按钮，尝试系统返回")
        self.handler.key_actions.press_back()

    def _create_party_flow(self) -> bool:
        key, element = self.handler.element_finder.wait_for_any_element(['create_party_entry', 'create_room_entry'])
        if not element:
            self.logger.warning("未找到派对入口")
            return False
        element.click()
        self.logger.info("Clicked create party entry")

        mode = self._party_create_mode()
        if mode == 'restore_party':
            wait_keys = ['restore_party', 'confirm_party', 'party_state_entry']
        else:
            wait_keys = ['new_party_entry', 'confirm_party', 'party_state_entry']
        key, element = self.handler.element_finder.wait_for_any_element(wait_keys)
        if not element:
            self.logger.warning("未找到派对创建或恢复按钮")
            return False

        if key == 'restore_party':
            element.click()
            self.logger.info("Clicked restore party entry")
            return True

        party_state_entry = None
        if key == 'new_party_entry' or key == 'confirm_party':
            element.click()
            self.logger.info(f"Clicked new party entry: {key}")
            party_state_entry = self.handler.element_finder.wait_for_element('party_state_entry')
        elif key == 'party_state_entry':
            party_state_entry = element

        if not party_state_entry:
            self.logger.warning("未找到创建派对屏幕")
            return False

        party_state_entry.click()
        self.logger.info("Clicked party state entry")

        close_party_notification = self.handler.element_finder.wait_for_element('close_party_notification')
        if not close_party_notification:
            self.logger.warning("未找到关闭派对推荐")
            return False
        close_party_notification.click()
        self.logger.info("Clicked close party notification")

        create_party_button = self.handler.element_finder.wait_for_element('create_party_button')
        if not create_party_button:
            self.logger.warning("<UNK>")
            return False
        create_party_button.click()
        self.logger.info("Clicked create party button")
        return True

    def _party_create_mode(self) -> str:
        mode = self.handler.config.get('party_create_mode', 'new_party_entry')
        if mode in ('new_party_entry', 'restore_party'):
            return mode
        self.logger.warning(f"未知 party_create_mode={mode}，回退 new_party_entry")
        return 'new_party_entry'

    async def _after_party_created(self) -> None:
        self.reset_party_time()
        self.logger.info("派对创建成功，准备设置默认notice")

        notice_manager = self.handler.controller.notice_manager
        result = await notice_manager.set_default_notice()
        if 'success' in result:
            self.logger.info("默认notice设置成功")
        else:
            self.logger.warning(f"默认notice设置失败: {result.get('error', 'Unknown error')}")

        seat_manager = self.handler.controller.seat_manager
        self.logger.info("Attempting to seat owner after party creation")
        result = await seat_manager.seating.find_owner_seat()
        if 'success' in result:
            self.logger.info("Owner successfully seated")
        else:
            self.logger.warning(f"Failed to seat owner: {result.get('error', 'Unknown error')}")

        automation = getattr(self.handler.controller, "post_party_create_automation", None)
        if automation:
            await automation.on_party_created_new()
        else:
            self.logger.warning("post_party_create_automation not initialized; skip auto commands")
