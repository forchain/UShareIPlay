import logging
import time

from .base import SeatManagerBase


class SeatUIManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.is_expanded = False

    def check_seats_state(self):
        """检查座位的实际展开状态并更新 is_expanded 标志"""
        if self.handler is None:
            # 避免引用None对象
            logging.getLogger('seat_ui').error("check_seats_state: handler 为 None")
            return self.is_expanded

        # 添加日志
        # self.handler.logger.info(f"检查座位状态，当前 is_expanded={self.is_expanded}")

        # 获取元素
        expand_seats = self.handler.try_find_element_plus('expand_seats', log=False)
        if not expand_seats:
            # self.handler.logger.warning("未找到座位按钮，无法确定当前状态")
            return self.is_expanded

        # 获取文本并根据文本判断状态
        actual_text = expand_seats.text
        # self.handler.logger.info(f"座位按钮文本为: '{actual_text}'")

        # 根据文本判断座位是否展开
        if '收起' in actual_text:
            if not self.is_expanded:
                self.handler.logger.info("检测到座位已展开，但状态标记为未展开，更新状态")
                self.is_expanded = True
        elif '展开' in actual_text:
            if self.is_expanded:
                self.handler.logger.info("检测到座位已收起，但状态标记为已展开，更新状态")
                self.is_expanded = False
        else:
            self.handler.logger.warning(f"座位按钮文本 '{actual_text}' 无法判断展开状态")

        return self.is_expanded

    def expand_seats(self):
        """Expand seats if collapsed"""
        if self.handler is None:
            self.handler.logger.error("expand_seats: handler 为 None")
            return False

        # 首先检查实际状态
        try:
            self.check_seats_state()
        except Exception as e:
            self.handler.logger.error(f"检查座位状态时出错: {str(e)}")

        if self.is_expanded:
            # self.handler.logger.info("座位已经展开，无需操作")
            return True

        # 添加详细日志，查看找到的元素
        # self.handler.logger.info("尝试展开座位...")
        try:
            expand_seats = self.handler.try_find_element_plus('expand_seats', log=False)

            # 记录按钮的实际文本内容
            if expand_seats:
                actual_text = expand_seats.text
                # self.handler.logger.info(f"找到座位按钮，其文本为: '{actual_text}'")

                # 检查文本是否包含展开字样，不强制匹配完整文本
                if '展开' in actual_text:
                    # self.handler.logger.info(f"检测到展开字样，点击按钮")
                    expand_seats.click()
                    self.handler.logger.info(f'Expanded seats')
                    self.is_expanded = True
                    time.sleep(0.5)  # Give time for animation
                    return True
                else:
                    self.handler.logger.warning(f"座位按钮文本不匹配预期，无法展开: '{actual_text}'")
                    return False
            else:
                self.handler.logger.warning("未找到座位按钮，无法展开座位")
                return False

        except Exception as e:
            self.handler.logger.error(f"展开座位时出错: {str(e)}")
            return False

    def _get_seat_number(self, container):
        """Get seat number from container"""
        try:
            # This is a placeholder - you'll need to implement the actual logic
            # to determine the seat number from the container
            return 1
        except:
            return None
