import time
import traceback
from typing import List, Dict, Optional


class RecoveryManager:
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self, handler):
        self.handler = handler
        self.logger = handler.logger

        # 关闭和返回按钮列表
        self.close_buttons = [
            'floating_entry',
            'party_back',
            'go_back',
            'close_app',
            'close_notice',
            'search_back',
            'close_more_menu',
            'activity_back',
            'h5_back',
            'close_button',
            'reminder_ok'  # 确认提醒按钮
        ]

        # 抽屉式弹窗列表
        self.drawer_elements = [
            'online_drawer',
            'share_drawer',
            'input_drawer'
        ]

        # 潜在风险元素列表（虽然不挡住输入框，但可能因误操作导致不稳定）
        self.risk_elements = [
            'new_message_tip',
            'close_button',
            'collapse_seats'
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
            input_box = self.handler.try_find_element_plus('room_id', log=False)
            return input_box is not None
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
                self.logger.info(f"发现关闭按钮: {button_key}，正在点击")
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
                self.logger.info(f"发现抽屉元素: {drawer_key}，正在点击关闭")
                # 点击抽屉上方区域来关闭抽屉
                self.handler.click_element_at(element, x_ratio=0.3, y_ratio=0, y_offset=-200)
                return True
            except Exception as e:
                self.logger.debug(f"检测抽屉元素 {drawer_key} 时出错: {str(e)}")
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

                self.logger.info(f"发现潜在风险元素: {risk_key}，正在处理")
                element.click()
                return True
            except Exception as e:
                self.logger.debug(f"检测风险元素 {risk_key} 时出错: {str(e)}")
                continue

        return False

    def handle_other_anomalies(self) -> bool:
        """
        处理其他可能的异常情况
        返回True表示执行了操作，False表示没有找到需要处理的情况
        """
        # 检测是否在搜索页面
        try:
            search_box = self.handler.try_find_element_plus('search_box', log=False)
            if search_box:
                self.logger.info("发现搜索框，尝试返回")
                # 尝试点击返回按钮
                back_button = self.handler.try_find_element_plus('search_back', log=False)
                if back_button and self.handler.click_element_at(back_button):
                    self.logger.info("成功从搜索页面返回")
                    return True
        except Exception as e:
            self.logger.debug(f"检测搜索页面时出错: {str(e)}")

        # 检测是否在派对大厅页面
        try:
            party_hall = self.handler.try_find_element_plus('party_hall', log=False)
            if party_hall:
                self.logger.info("发现派对大厅页面，尝试创建或加入派对")
                # 尝试点击创建派对按钮
                create_button = self.handler.try_find_element_plus('create_party_entry', log=False)
                if create_button and self.handler.click_element_at(create_button):
                    self.logger.info("成功点击创建派对按钮")
                    return True
        except Exception as e:
            self.logger.debug(f"检测派对大厅页面时出错: {str(e)}")

        # 检测是否在首页（非派对页面）
        try:
            square_tab = self.handler.try_find_element_plus('square_tab', log=False)
            if square_tab:
                self.logger.info("发现首页，尝试进入派对")
                # 尝试点击派对标签
                party_tab = self.handler.try_find_element_plus('party_tab', log=False)
                if party_tab and self.handler.click_element_at(party_tab):
                    self.logger.info("成功点击派对标签")
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

        # 1. 处理潜在风险元素（优先级最高，在正常状态检测之前）
        recovery_performed = self.handle_risk_elements()
        if recovery_performed:
            self.last_recovery_time = current_time
            return True

        # 首先检查是否处于正常状态
        if self.is_normal_state():
            return False

        # 执行恢复操作，一次只处理一个异常情况
        self.logger.info("检测到异常状态，开始执行恢复操作")

        # 2. 处理关闭按钮
        if not recovery_performed:
            recovery_performed = self.handle_close_buttons()

        # 3. 处理抽屉元素
        if not recovery_performed:
            recovery_performed = self.handle_drawer_elements()

        # 4. 处理其他可能的异常情况
        if not recovery_performed:
            recovery_performed = self.handle_other_anomalies()

        if recovery_performed:
            self.last_recovery_time = current_time
            self.logger.info("恢复操作执行完成，等待下次检查")

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
