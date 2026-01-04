import asyncio
import time

from ..core.singleton import Singleton
from ..models.message_info import MessageInfo


class RecoveryManager(Singleton):
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ..handlers.soul_handler import SoulHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger
        self.last_recovery_time = 0
        self.recovery_cooldown = 5  # 5秒冷却时间
        self.manual_mode_enabled = False  # 手动模式标志位
        self.abnormal_state_detected = False  # 异常状态检测标志
        self.abnormal_state_count = 0  # 连续异常状态计数
        self._party_manager = None  # 延迟初始化，避免循环依赖

        # 关闭和返回按钮列表
        self.close_buttons = [
            'floating_entry',
            'party_ended',

            # 如果无法用返回键，则在此添加
            'confirm_close_3',

            # 如果用返回键会造成潜在问题，则在此添加

            # 可以用返回按钮代替，暂时不检查，提高效率
            # 'party_hall_back',
            # 'search_back',
            # 'close_more_menu',

            # 不确定是否可以用返回键代替
            # 'reload_button',
            # 'close_chat',
            # 'confirm_close_6',
            # 'confirm_close_7',
            # 'confirm_close_4',
            # 'confirm_close_5',
            # 'confirm_close_1',
            # 'confirm_close_2',
            # 'confirm_close',

            # 'go_back',
            # 'go_back_1',
            # 'go_back_2',
            # 'close_notice',
            # 'close_notice_1',
            # 'h5_back',
            # 'receive_gift',
            # 'party_back',
            # 'close_app',
            # 'activity_back',
            # 'reminder_ok',
            # 'profile_back',
        ]

        # 抽屉式弹窗列表
        self.drawer_elements = [
            # 无法用返回键代替
            'input_drawer',

            # 不确定是否可以被返回键代替
            # 'party_restore_drawer'
            # 'bottom_drawer_1',
            # 'online_drawer',

            # 可以被返回键代替
            # 'share_drawer',
        ]

        # 潜在风险元素列表（虽然不挡住输入框，但可能因误操作导致不稳定）
        self.risk_elements = [
            'claim_reward_button',
            'new_message_tip',
            'close_button',
            'collapse_seats',
        ]

        # 正常状态的关键元素
        self.normal_state_elements = [
            'input_box_entry'
        ]

        self.last_recovery_time = 0
        self.recovery_cooldown = 1  # 恢复操作冷却时间（秒）

    @property
    def party_manager(self):
        """Lazy load PartyManager instance"""
        if self._party_manager is None:
            from ..managers.party_manager import PartyManager
            self._party_manager = PartyManager.instance()
        return self._party_manager

    def _set_default_notice(self):
        """设置默认notice（使用NoticeManager）"""
        try:
            from .notice_manager import NoticeManager
            notice_manager = NoticeManager.instance()
            result = notice_manager.set_default_notice()

            if 'success' in result:
                self.logger.info("默认notice设置成功")
                return True
            else:
                self.logger.warning(f"默认notice设置失败: {result.get('error', 'Unknown error')}")
                return False

        except Exception as e:
            self.logger.error(f"设置默认notice时出错: {str(e)}")
            return False

    def _seat_owner_after_party_creation(self):
        """Seat the owner after party creation/restoration"""
        try:
            time.sleep(1.5)  # Wait for party UI to stabilize

            from ..managers.seat_manager import seat_manager
            self.logger.info("Attempting to seat owner after party creation")
            result = seat_manager.seating.find_owner_seat()

            if 'success' in result:
                self.logger.info("Owner successfully seated")
                return True
            else:
                self.logger.warning(f"Failed to seat owner: {result.get('error', 'Unknown error')}")
                return False
        except Exception as e:
            self.logger.error(f"Error seating owner: {str(e)}")
            return False

    def _execute_radio_after_creation(self):
        """创建房间后执行 radio 命令"""
        try:
            if not hasattr(self.handler, 'controller') or not hasattr(self.handler.controller, 'radio_command'):
                self.logger.warning("Radio command not available, skipping")
                return

            # 创建 MessageInfo 对象
            message_info = MessageInfo(
                content="radio",
                nickname="Joyer",
                avatar_element=None,
                relation_tag=False
            )

            async def _run_radio():
                try:
                    # 执行 radio 命令（默认 collection，参数为空列表）
                    await self.handler.controller.radio_command.process(message_info, [])
                    self.logger.info("Radio command executed after party creation")
                except Exception as e:
                    self.logger.error(
                        f"Radio command task failed after party creation: {str(e)}"
                    )

            # 当前 check_and_recover 是在已有事件循环中被调用的，这里不能再用 asyncio.run
            loop = asyncio.get_running_loop()
            loop.create_task(_run_radio())
        except Exception as e:
            self.logger.error(f"Failed to execute radio command after party creation: {str(e)}")

    def is_normal_state(self) -> bool:
        """
        检测是否处于正常状态
        最快速的方法就是检测输入框是否存在
        """
        try:
            # 从 InfoManager 获取房间ID
            from .info_manager import InfoManager
            info_manager = InfoManager.instance()
            room_id_text = info_manager.room_id
            
            if room_id_text is None:
                return False

            if not room_id_text.startswith("FM"):
                self.logger.warning(f"Room ID:{room_id_text} does not start with FM, skip")
                return True

            party_id = self.handler.config.get('default_party_id')
            return room_id_text == party_id
        except Exception as e:
            self.logger.debug(f"检测正常状态时出错: {str(e)}")
            return False

    def mark_abnormal_state(self):
        """
        标记检测到异常状态（无消息）
        增加异常状态计数
        """
        if self.manual_mode_enabled:
            return False

        self.abnormal_state_detected = True
        self.abnormal_state_count += 1
        self.logger.debug(f"Marked abnormal state (count: {self.abnormal_state_count})")
        return True

    def handle_close_buttons(self) -> bool:
        """
        检测并点击各种关闭或返回按钮
        返回True表示执行了操作，False表示没有找到需要处理的按钮
        """
        for button_key in self.close_buttons:
            try:
                element = self.handler.try_find_element_plus(button_key, log=False)
                if not element:
                    continue
                self.logger.info(f"Clicked close button: {button_key}")
                element.click()
                return True
            except Exception as e:
                self.logger.error(f"Error on detecting close button {button_key}: {str(e)}")
                continue

        return False

    def handle_drawer_elements(self) -> bool:
        """
        检测并关闭各种抽屉式弹窗界面
        返回True表示执行了操作，False表示没有找到需要处理的抽屉
        """
        import time

        for drawer_key in self.drawer_elements:
            try:
                element = self.handler.try_find_element_plus(drawer_key, log=False)
                if not element:
                    continue

                # 添加超时保护
                start_time = time.time()
                click_success = self.handler.click_element_at(element, x_ratio=0.3, y_ratio=0, y_offset=-200)
                elapsed_time = time.time() - start_time

                if elapsed_time > 2:  # 如果点击操作超过2秒
                    self.logger.warning(f"Drawer click operation took {elapsed_time:.2f}s for {drawer_key}")

                if click_success:
                    self.logger.info(f"Closed drawer: {drawer_key}")
                    return True
                else:
                    self.logger.warning(f"Failed to close drawer: {drawer_key}")

            except Exception as e:
                self.logger.debug(f"Error on detecting drawer {drawer_key}: {str(e)}")
                continue

        return False

    def handle_risk_elements(self) -> bool:
        """
        检测并处理潜在风险元素
        这些元素虽然不直接影响输入框，但可能因误操作导致界面不稳定
        返回True表示执行了操作，False表示没有找到需要处理的元素
        """
        for risk_key in self.risk_elements:
            try:
                element = self.handler.try_find_element_plus(risk_key, log=False)
                if not element:
                    continue

                element.click()
                self.logger.info(f"Processed risk element: {risk_key}")
                return True
            except Exception as e:
                self.logger.error(f"Error on detecting on risk element: {risk_key} : {str(e)}")
                continue

        return False

    def handle_join_party(self) -> bool:
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
                ['confirm_party', 'restore_party', 'create_party_button'])
            if not element:
                self.logger.warning("未找到派对创建或恢复按钮")

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

    def check_and_recover(self) -> bool:
        """
        检查异常状态并执行恢复操作
        返回True表示执行了恢复操作，False表示状态正常或无需恢复
        """
        current_time = time.time()

        # 检查冷却时间
        if current_time - self.last_recovery_time < self.recovery_cooldown:
            return False

        # 如果启用了手动模式，跳过自动恢复
        if self.manual_mode_enabled:
            return False

        self.handler.switch_to_app()

        # 首先检查是否处于正常状态
        if self.is_normal_state():
            # 如果状态正常，重置异常状态标记
            if self.abnormal_state_detected:
                self.logger.info("State returned to normal, resetting abnormal state flags")
                self.abnormal_state_detected = False
                self.abnormal_state_count = 0
            return False
        # 找不到房名可能因为房名还没显示，不能认为是异常状态
        # else:
        #     self.mark_abnormal_state()

        if not self.abnormal_state_detected:
            return False

        # 如果检测到异常状态（无消息），优先执行恢复操作
        self.logger.warning(f"Abnormal state detected (count: {self.abnormal_state_count}), attempting recovery")

        # 1. 优先处理退出的情况
        recovery_performed = self.handle_join_party()

        # 2. 处理关闭按钮
        if not recovery_performed:
            recovery_performed = self.handle_close_buttons()

        # 3. 处理抽屉元素
        if not recovery_performed:
            recovery_performed = self.handle_drawer_elements()

        # 4. 如果还是无法恢复，尝试按返回键
        if not recovery_performed:
            self.logger.info("Attempting to press back button to exit abnormal state")
            self.handler.press_back()
            recovery_performed = True

        if recovery_performed:
            self.last_recovery_time = current_time
            self.abnormal_state_count = 0  # 重置计数
            self.logger.info("Recovery operation completed for abnormal state")

        return recovery_performed

    def force_recovery(self) -> bool:
        """
        强制执行恢复操作，忽略冷却时间
        用于紧急情况下的恢复
        """
        self.logger.warning("执行强制恢复操作")
        self.last_recovery_time = 0  # 重置冷却时间
        return self.check_and_recover()

    def set_manual_mode(self, enabled: bool):
        """
        设置手动模式状态
        Args:
            enabled: True表示启用手动模式（禁用自动恢复），False表示禁用手动模式（启用自动恢复）
        """
        self.manual_mode_enabled = enabled
        self.logger.info(f"Recovery manager manual mode set to: {enabled}")
