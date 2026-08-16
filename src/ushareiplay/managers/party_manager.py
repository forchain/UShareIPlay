import time
import traceback
from datetime import datetime
from typing import Any, Optional

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
            if MessageDispatch.is_initialized():
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
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized() and RoomState.instance().is_guest_room:
                return

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
            if self.message_dispatch:
                try:
                    self.message_dispatch.send_screen_message('Ending party')
                except Exception as msg_e:
                    self.logger.debug(f"Failed to send screen message: {msg_e}")

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

                # Click end/exit party option (房主为"关闭派对"，客房为"退出派对")
                exit_key, exit_elem = self.handler.element_finder.wait_for_any_element(
                    ['exit_party_item', 'end_party']
                )
                if not exit_elem:
                    return {'error': 'Failed to find end/exit party option'}
                exit_elem.click()
                self.logger.info(f"Clicked {exit_key} option")

            # Click confirm (房主为"解散派对"，客房为"退出派对"，或通用"确定"/"确认")
            confirm_key, confirm_elem = self.handler.element_finder.wait_for_any_element(
                ['confirm_exit_party', 'confirm_end', 'confirm_close', 'confirm_mic', 'confirm_btn']
            )
            if not confirm_elem:
                return {'error': 'Failed to find confirm end/exit button'}
            confirm_elem.click()
            self.logger.info(f"Clicked confirm button: {confirm_key}")

            # Reset state after ending/exiting party
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized():
                RoomState.instance().expected_party_id = None
                RoomState.instance().clear()
            self.handler.party_id = None

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

    def _restore_current_party(self) -> bool:
        """安全返回当前派对（通过悬浮窗/返回入口恢复当前房间）"""
        try:
            keys = ['private_room_entry', 'floating_entry', 'party_back']
            key, element = self.handler.element_finder.wait_for_any_element(keys, timeout=2)
            if element:
                element.click()
                self.logger.info(f"Restored current party via {key}")
                return True

            search_back = self.handler.element_finder.try_find_element('search_back', log=False)
            if search_back:
                search_back.click()
                self.logger.info("Clicked search_back before restoring party")
            elif hasattr(self.handler.key_actions, 'press_back'):
                self.handler.key_actions.press_back()

            key, element = self.handler.element_finder.wait_for_any_element(keys, timeout=2)
            if element:
                element.click()
                self.logger.info(f"Restored current party via {key} after back")
                return True

            self.logger.warning("未能找到恢复派对的悬浮窗入口")
            return False
        except Exception as e:
            self.logger.warning(f"Error restoring current party: {e}")
            return False

    def _navigate_back_to_hall_entry(self, max_attempts: int = 5) -> bool:
        """
        不断返回直到找到进入建房/派对大厅的入口并进入派对大厅（确保进入后 search_entry 可点击）
        """
        for attempt in range(max_attempts):
            # 1. 如果已经在派对大厅且搜索按钮可用，直接返回 True
            if self.handler.element_finder.try_find_element('search_entry', log=False):
                self.logger.info("Already at search entry")
                return True

            # 2. 如果在首页（星球页），尝试从首页进入派对大厅
            if self._enter_party_hall_from_home():
                if self.handler.element_finder.wait_for_element_clickable('search_entry'):
                    self.logger.info("Successfully entered party hall from home")
                    return True

            # 3. 检查是否有单独的派对大厅入口 (party_hall_entry)
            party_hall_entry = self.handler.element_finder.try_find_element('party_hall_entry', log=False)
            if party_hall_entry:
                party_hall_entry.click()
                self.logger.info("Clicked party_hall_entry directly")
                if self.handler.element_finder.wait_for_element_clickable('search_entry'):
                    return True

            # 4. 若不在首页或大厅，尝试返回上一级（排除 party_hall_back，避免误退出大厅）
            self.logger.info(f"Navigating back to find hall entry (attempt {attempt + 1}/{max_attempts})")
            back_keys = [
                'item_left_back', 'titlebar_back_ivbtn', 'go_back', 'go_back_1',
                'h5_back', 'group_back', 'close_button', 'close_btn', 'activity_back'
            ]
            back_key, back_elem = self.handler.element_finder.wait_for_any_element(back_keys, timeout=1)
            if back_elem:
                back_elem.click()
                self.logger.info(f"Clicked back button: {back_key}")
            elif hasattr(self.handler.key_actions, 'press_back'):
                self.handler.key_actions.press_back()
                self.logger.info("Pressed system back key")

        # 最终尝试一次
        if self._enter_party_hall_from_home():
            return bool(self.handler.element_finder.wait_for_element_clickable('search_entry'))
        return bool(self.handler.element_finder.try_find_element('search_entry', log=False))

    def _search_party(self, party_id: str) -> bool:
        """进入派对搜索并输入 party_id 点击搜索"""
        search_entry = self.handler.element_finder.wait_for_element_clickable('search_entry')
        if not search_entry:
            return False
        search_entry.click()
        self.logger.info("Clicked search entry")

        search_box = self.handler.element_finder.wait_for_element_clickable('search_box')
        if not search_box:
            return False
        search_box.send_keys(party_id)
        self.logger.info(f"Entered party ID: {party_id}")

        search_button = self.handler.element_finder.wait_for_element_clickable('search_button')
        if not search_button:
            return False
        search_button.click()
        self.logger.info("Clicked search button")
        return True

    def _check_target_party_online(self) -> tuple[Optional[Any], Optional[Any]]:
        """检查搜索结果中的 room_card 与 party_online，返回 (room_card, party_online)"""
        key, result_element = self.handler.element_finder.wait_for_any_element(
            ['party_online', 'room_card', 'parties_search', 'party_search_empty', 'no_party_from_hall'], timeout=5
        )

        room_card = self.handler.element_finder.try_find_element('room_card', log=False)
        if not room_card:
            if key == 'parties_search' and result_element:
                room_card = self.handler.element_finder.find_child_element(result_element, 'party_id') or \
                            self.handler.element_finder.find_child_element(result_element, 'room_card') or result_element
            elif key in ('party_online', 'room_card') and result_element:
                room_card = result_element

        party_online = self.handler.element_finder.try_find_element('party_online', log=False)
        if not party_online:
            if key == 'party_online' and result_element:
                party_online = result_element
            elif key == 'parties_search' and result_element:
                party_online = self.handler.element_finder.find_child_element(result_element, 'party_online') or \
                               self.handler.element_finder.find_child_element(result_element, 'party_id')

        return room_card, party_online

    async def invite_user(self, message_info: MessageInfo, party_id: str) -> dict:
        """
        邀请当前账号加入指定派对（切房前先校验目标房间是否开启；若开启则先回房间关闭当前房间，再进入目标房间）
        Args:
            message_info: 消息信息（用于等级校验和返回展示）
            party_id: 目标派对ID
        Returns:
            dict: 包含处理结果的字典
        """
        try:
            # 1. 优先点击最小化房间按钮 (ivChatZoomIn)
            minimize_btn = self.handler.element_finder.try_find_element('minimize_room', log=False)
            if minimize_btn:
                minimize_btn.click()
                self.logger.info("Clicked minimize_room button (ivChatZoomIn)")

            # 2. 导航至派对大厅
            if not self.handler.element_finder.try_find_element('search_entry', log=False):
                if not self._navigate_back_to_hall_entry():
                    more_menu = self.handler.element_finder.try_find_element('more_menu', log=False)
                    if more_menu:
                        more_menu.click()
                        self.logger.info("Clicked more menu button as fallback")
                        self.handler.element_finder.wait_for_element('more_menu_container')
                        party_hall = self.handler.element_finder.wait_for_element_clickable('party_hall')
                        if party_hall:
                            party_hall.click()
                            self.logger.info("Clicked party hall entry from more menu")

            # 3. 搜索目标房间
            if not self._search_party(party_id):
                self._restore_current_party()
                return {
                    'error': 'Failed to find search entry or search box',
                    'party_id': party_id
                }

            # 4. 检查目标房间是否开启（必须在线）
            room_card, party_online = self._check_target_party_online()
            if not room_card or not party_online:
                self.logger.warning(f"Target party {party_id} is closed or not found, restoring previous party")
                self._restore_current_party()
                return {
                    'error': f'Party {party_id} is closed or not found',
                    'party_id': party_id
                }

            # 5. 目标房间已确认开启：先返回当前房间并正式关闭当前房间
            self.logger.info(f"Target party {party_id} is open. Restoring and closing current party...")
            self._restore_current_party()
            self.end_party()

            # 6. 关闭当前房间后，重新前往派对大厅搜索并进入目标房间
            self.logger.info(f"Current party closed. Navigating to hall to enter target party {party_id}...")
            if not self.handler.element_finder.try_find_element('search_entry', log=False):
                self._navigate_back_to_hall_entry()

            if not self._search_party(party_id):
                return {
                    'error': f'Failed to search party {party_id} after closing previous room',
                    'party_id': party_id
                }

            # 7. 等待搜索结果中的 room_card 并点击进入目标房间
            room_card = self.handler.element_finder.wait_for_element_clickable('room_card')
            if not room_card:
                room_card, _ = self._check_target_party_online()

            if not room_card:
                return {
                    'error': f'Failed to locate room card for party {party_id}',
                    'party_id': party_id
                }

            room_card.click()
            self.logger.info(f"Clicked room_card to enter target party {party_id}")

            # 若弹出确认提示，自动确认
            confirm_key, confirm_btn = self.handler.element_finder.wait_for_any_element(
                ['confirm_exit_party', 'confirm_end', 'confirm_close', 'confirm_mic', 'confirm_btn'], timeout=2
            )
            if confirm_btn:
                confirm_btn.click()
                self.logger.info(f"Confirmed room switch dialog ({confirm_key})")

            # 8. 进入后自动抢麦并更新 party_id 与 RoomState (含预期目标ID)
            self.handler.grab_mic_and_confirm()
            self.handler.party_id = party_id
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized():
                RoomState.instance().expected_party_id = party_id
                RoomState.instance().room_id = party_id
            return {'party_id': party_id, 'user': message_info.nickname}

        except Exception as e:
            self.logger.error(f"Error inviting to party: {traceback.format_exc()}")
            self._restore_current_party()
            return {
                'error': str(e),
                'party_id': party_id
            }

    async def leave_and_recreate_party(self) -> bool:
        """
        当检测到当前房间与预期房间不匹配（例如被系统自动调入随机房间）时：
        1. 退出当前随机房间
        2. 清空预期客房 ID 并恢复为默认主房间
        3. 重新进入派对大厅，搜索默认房间或创建新房间
        """
        self.logger.warning("Leaving unexpected/unauthorized room and returning to home to recreate party...")
        try:
            self.end_party()
        except Exception as e:
            self.logger.warning(f"Error while leaving unexpected room: {e}")

        from ushareiplay.state.room_state import RoomState
        if RoomState.is_initialized():
            RoomState.instance().expected_party_id = None
            RoomState.instance().clear()
        self.handler.party_id = None

        return await self.join_party()

    async def join_party(self) -> bool:
        """
        处理其他可能的异常情况
        返回True表示执行了操作，False表示没有找到需要处理的情况
        """
        try:
            if not self._enter_party_hall_from_home():
                return False

            # 发现首页并进入大厅，说明已离开前一个房间（无论原为主房还是客房），清空旧房间状态
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized():
                RoomState.instance().clear()
            self.handler.party_id = None

            if self._search_and_try_enter_existing_party():
                from ushareiplay.managers.recommendation_manager import RecommendationManager
                if RecommendationManager.is_initialized():
                    RecommendationManager.instance().ensure_synced_on_return()
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

        default_party_id = (
            self.handler.config.get('soul', {}).get('default_party_id')
            or self.handler.config.get('default_party_id')
        )
        party_id = default_party_id or self.handler.party_id
        if not party_id:
            self.logger.warning("未配置 default_party_id，直接准备创建派对")
            self._go_back_from_search()
            return False

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
            room_card.click()
            self.logger.info("Clicked room card")
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

        party_recommend_config = bool(self.handler.config.get('create_party_recommendation', True))
        if not party_recommend_config:
            party_state_entry = element if key == 'party_state_entry' else self.handler.element_finder.wait_for_element('party_state_entry')
            if not party_state_entry:
                self.logger.warning("未找到派对状态入口按钮")
                return False
            party_state_entry.click()
            self.logger.info("Clicked party state entry to disable recommendation")
            close_party_notification = self.handler.element_finder.wait_for_element('close_party_notification')
            if not close_party_notification:
                self.logger.warning("未找到关闭派对推荐")
                return False
            close_party_notification.click()
            self.logger.info("Clicked close party notification")
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized():
                RoomState.instance().recommendation_enabled = False
        else:
            self.logger.info("Keep party recommendation enabled as configured (default '所有人')")
            from ushareiplay.state.room_state import RoomState
            if RoomState.is_initialized():
                RoomState.instance().recommendation_enabled = True

        change_party_type = bool(self.handler.config.get('change_party_type', True))
        if change_party_type:
            party_type_chat = self.handler.element_finder.wait_for_element('party_type_chat')
            if not party_type_chat:
                self.logger.warning("未找到闲聊唠嗑派对类型按钮")
                return False
            party_type_chat.click()
            self.logger.info("Clicked party type chat entry (闲聊唠嗑)")

            target_type_key = self.handler.config.get('target_party_type_element', 'party_type_singing')
            party_type_target = self.handler.element_finder.wait_for_element(target_type_key)
            if not party_type_target:
                self.logger.warning(f"未找到目标派对类型按钮: {target_type_key}")
                return False
            party_type_target.click()
            self.logger.info(f"Clicked target party type entry ({target_type_key})")

        create_party_button = self.handler.element_finder.wait_for_element('create_party_button')
        if not create_party_button:
            self.logger.warning("未找到创建房间按钮")
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
        from ushareiplay.state.room_state import RoomState
        if RoomState.is_initialized():
            RoomState.instance().expected_party_id = None
            RoomState.instance().room_id = self.handler.party_id
            RoomState.instance().is_guest_room = False
        self.logger.info("派对创建成功，准备设置默认notice")

        notice_manager = self.handler.controller.notice_manager
        result = await notice_manager.set_default_notice()
        if 'success' in result:
            self.logger.info("默认notice设置成功")
        else:
            self.logger.warning(f"默认notice设置失败: {result.get('error', 'Unknown error')}")

        seat_manager = self.handler.controller.seat_manager
        self.logger.info("Attempting to seat owner after party creation")
        result = await seat_manager.find_owner_seat()
        if 'success' in result:
            self.logger.info("Owner successfully seated")
        else:
            self.logger.warning(f"Failed to seat owner: {result.get('error', 'Unknown error')}")

        automation = getattr(self.handler.controller, "post_party_create_automation", None)
        if automation:
            await automation.on_party_created_new()
        else:
            self.logger.warning("post_party_create_automation not initialized; skip auto commands")

    def ensure_room_info_window_closed(self) -> None:
        """
        检查并确保房间信息窗口/分类弹窗已被关闭，恢复至主房间界面。
        优先使用 UI 正规关窗操作 (RecoveryManager.close_drawer('slide_drawer'))；
        仅在抽屉关窗未成功且弹窗标志依然存留时，才使用 press_back() 作为最后的保底防御，
        防止因过快盲按 press_back() 导致误退出派对房间的风险。
        """
        try:
            is_dialog_open = False
            for key in ['party_room_type_option', 'party_recommendation_status', 'edit_topic_entry', 'edit_notice_entry', 'slide_drawer']:
                if self.handler.element_finder.try_find_element(key, log=False):
                    is_dialog_open = True
                    break

            if not is_dialog_open:
                return

            self.logger.info("Room info window is open, attempting to close via close_drawer UI action")
            from ushareiplay.managers.recovery_manager import RecoveryManager
            if RecoveryManager.is_initialized():
                closed = RecoveryManager.instance().close_drawer('slide_drawer')
                if closed:
                    self.logger.info("Successfully closed room info window via close_drawer")
                    return

            self.logger.warning("close_drawer did not close room info window, falling back to press_back")
            self.handler.key_actions.press_back()
        except Exception as e:
            self.logger.warning(f"Error ensuring room info window closed: {e}")

    def check_and_correct_room_type(self, auto_close: bool = True) -> dict:
        """
        在派对房间内检查并校正房间类型。
        点击房间标题打开房间信息窗口，读取 tv_type 文本；
        如文本为“闲聊唠嗑”，自动点击进入二级弹窗切为“唱歌听歌”（选择后自动返回）。
        完成或退出时通过 ensure_room_info_window_closed 保证窗口彻底关闭。

        Args:
            auto_close: 是否在完成后自动关闭房间信息窗口 (默认 True)
        """
        try:
            type_elem = self.handler.element_finder.try_find_element('party_room_type_option', log=False)
            if not type_elem:
                room_topic = self.handler.element_finder.wait_for_element_clickable('room_topic')
                if not room_topic:
                    return {'error': 'Failed to find room topic entry'}
                room_topic.click()
                self.logger.info("Clicked room_topic to open room info window")
                type_elem = self.handler.element_finder.wait_for_element('party_room_type_option')

            if not type_elem:
                self.logger.warning("未找到房间类型选项 (party_room_type_option)")
                return {'error': 'Failed to find party_room_type_option'}

            current_type_text = (getattr(type_elem, 'text', '') or "").strip()
            self.logger.info(f"Inspected in-room party type: '{current_type_text}'")

            if "闲聊唠嗑" in current_type_text or current_type_text == "闲聊唠嗑":
                self.logger.info("Party type is '闲聊唠嗑', attempting to switch to '唱歌听歌'")
                type_elem.click()

                target_type_key = self.handler.config.get('target_party_type_element', 'party_type_singing')
                target_elem = self.handler.element_finder.wait_for_element(target_type_key)
                if not target_elem:
                    self.logger.warning(f"未找到目标房间类型按钮 ({target_type_key})")
                    return {'error': f'Failed to find target party type button ({target_type_key})'}

                target_elem.click()
                self.logger.info(f"Successfully clicked target party type ({target_type_key})")
                return {'success': True, 'switched': True}
            else:
                self.logger.info(f"Party type already target/different ('{current_type_text}'), no switch needed")
                return {'success': True, 'switched': False}
        except Exception as e:
            self.logger.error(f"Error checking/correcting room type: {traceback.format_exc()}")
            return {'error': str(e)}
        finally:
            if auto_close:
                self.ensure_room_info_window_closed()

    def sync_and_correct_room_type_if_dialog_open(self) -> dict:
        """
        被动纠偏：当房间信息窗口因任何原因（如更新标题/主题/公告/推荐）打开时被动调用。
        读取当前 UI 中的 party_room_type_option，若为“闲聊唠嗑”则修正为“唱歌听歌”，
        选择后自动返回并保持在房间信息窗口中（不自动关窗，供后续修改/检查使用）。
        """
        type_elem = self.handler.element_finder.try_find_element('party_room_type_option', log=False)
        if not type_elem:
            return {'skipped': True, 'reason': 'dialog_not_open'}
        return self.check_and_correct_room_type(auto_close=False)


