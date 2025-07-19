import time
from typing import Dict


class RecoveryManager:
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self, handler):
        self.handler = handler
        self.logger = handler.logger

        # 关闭和返回按钮列表
        self.close_buttons = [
            'receive_gift',
            'floating_entry',
            'party_hall_back',
            'party_back',
            'go_back',
            'close_app',
            'close_notice',
            'search_back',
            'close_more_menu',
            'activity_back',
            'h5_back',
            'reminder_ok',
        ]

        # 抽屉式弹窗列表
        self.drawer_elements = [
            'online_drawer',
            'share_drawer',
            'input_drawer',
            'party_restore_drawer'
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

    def is_normal_state(self) -> bool:
        """
        检测是否处于正常状态
        最快速的方法就是检测输入框是否存在
        """
        try:
            room_id = self.handler.try_find_element_plus('room_id', log=False)
            party_id = self.handler.config.get('default_party_id')
            return room_id is not None and room_id.text == party_id
        except Exception as e:
            self.logger.debug(f"检测正常状态时出错: {str(e)}")
            return False

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
                self.logger.warning(f"发现关闭按钮: {button_key}，正在点击")
                element.click()
                return True
            except Exception as e:
                self.logger.debug(f"检测关闭按钮 {button_key} 时出错: {str(e)}")
                continue

        return False

    def handle_drawer_elements(self) -> bool:
        """
        检测并关闭各种抽屉式弹窗界面
        返回True表示执行了操作，False表示没有找到需要处理的抽屉
        """
        for drawer_key in self.drawer_elements:
            try:
                element = self.handler.try_find_element_plus(drawer_key, log=False)
                if not element:
                    continue

                self.handler.click_element_at(element, x_ratio=0.3, y_ratio=0, y_offset=-200)
                self.logger.info(f"Closed drawer: {drawer_key}")
                return True
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

            if party_id := self.handler.party_id:
                if not self._search_and_enter_party(party_id):
                    self.logger.warning("未找到派对")
                    return False

            key, element = self.handler.wait_for_any_element_plus(
                ['party_back', 'create_party_entry', 'create_room_entry'])
            if not element:
                self.logger.warning("未找到派对入口")
                return False

            if key == 'party_back':
                element.click()
                self.logger.info("Clicked back to party")
                return True

            element.click()
            self.logger.info("Clicked create party entry")

            key, element = self.handler.wait_for_any_element_plus(
                ['confirm_party', 'restore_party', 'create_party_button'])
            if not element:
                self.logger.warning("未找到派对创建或恢复按钮")
                return False

            if key == 'create_party_button':
                element.click()
                self.logger.info("Clicked create party button")
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

        self.handler.switch_to_app()

        # 1. 处理潜在风险元素（优先级最高，在正常状态检测之前）
        self.handle_risk_elements()

        # 首先检查是否处于正常状态
        if self.is_normal_state():
            return False

        # 2. 处理关闭按钮
        recovery_performed = self.handle_close_buttons()

        # 3. 处理抽屉元素
        if not recovery_performed:
            recovery_performed = self.handle_drawer_elements()

        # 4. 处理其他可能的异常情况
        if not recovery_performed:
            recovery_performed = self.handle_join_party()

        if recovery_performed:
            self.last_recovery_time = current_time
            # self.logger.info("恢复操作执行完成，等待下次检查")

        return recovery_performed

    def force_recovery(self) -> bool:
        """
        强制执行恢复操作，忽略冷却时间
        用于紧急情况下的恢复
        """
        self.logger.warning("执行强制恢复操作")
        self.last_recovery_time = 0  # 重置冷却时间
        return self.check_and_recover()

    def get_status_info(self) -> Dict:
        """
        获取恢复管理器的状态信息
        """
        return {
            'is_normal_state': self.is_normal_state(),
            'last_recovery_time': self.last_recovery_time,
            'recovery_cooldown': self.recovery_cooldown,
            'close_buttons': self.close_buttons,
            'drawer_elements': self.drawer_elements,
            'risk_elements': self.risk_elements
        }
