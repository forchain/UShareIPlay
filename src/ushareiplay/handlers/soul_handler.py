import logging

from ushareiplay.managers.message_manager import MessageManager
from ushareiplay.core.app_handler import AppHandler
from ushareiplay.core.singleton import Singleton


class SoulHandler(AppHandler, Singleton):
    # 抢麦后就座动画/界面刷新的等待上限（秒）
    SEAT_SETTLE_TIMEOUT = 3.0

    def __init__(self, driver, config, controller):
        logging.getLogger('SoulHandler').debug("SoulHandler.__init__ 开始")
        super().__init__(driver, config, controller)
        self.logger.debug("SoulHandler AppHandler 初始化完成")
        # 延迟初始化 message_manager，避免循环依赖
        self._message_manager = None
        self.previous_message_ids = set()  # Store previous element IDs
        self.party_id = None
        self.last_content = None  # Last message content
        self.second_last_content = None  # Second last message content
        self.logger.debug("SoulHandler.__init__ 完成")

    @property
    def message_manager(self):
        """延迟获取 MessageManager 实例"""
        if self._message_manager is None:
            self._message_manager = MessageManager.instance()
        return self._message_manager

    def is_chat_window_open(self) -> bool:
        """检查聊天输入窗口是否打开/可见。

        当 input_box (cn.soulapp.android:id/etInputView) 在界面呈现时，
        表示聊天窗口处于打开状态。
        """
        input_box = self.element_finder.try_find_element('input_box', log=False)
        if not input_box:
            return False
        try:
            return bool(input_box.is_displayed())
        except Exception:
            return False

    def ensure_chat_window_closed(
        self, timeout: float = 1.0, max_back_attempts: int = 2, input_element=None
    ) -> bool:
        """确保聊天输入窗口已被关闭，恢复至房间主界面。

        输入消息后，若聊天窗口未正常关闭会遮挡公屏消息并阻塞后续消息检测。
        1. 若聊天窗口当前处于打开状态，首先尝试常规 UI 操作（点击输入框外部空白区域）；
        2. 动态等待输入框消失（wait_for_element_disappear）；
        3. 若仍未消失，以 press_back() 作为保底兜底（最多尝试 max_back_attempts 次，分别针对软键盘与输入弹窗）；
        4. 确认输入框彻底不可见后返回 True。
        """
        if input_element is not None:
            try:
                if not input_element.is_displayed():
                    return True
            except Exception:
                input_element = None

        if input_element is None and not self.is_chat_window_open():
            return True

        self.logger.info("Chat window is open, attempting to close it")

        target_box = input_element or self.element_finder.try_find_element('input_box', log=False)
        if target_box:
            try:
                self.gesture_handler.click_element_at(
                    target_box, x_ratio=0.5, y_ratio=0, y_offset=-200
                )
            except Exception as e:
                self.logger.debug(f"Failed to click outside input box: {e}")

        if hasattr(self.element_finder, 'wait_for_element_disappear'):
            if self.element_finder.wait_for_element_disappear('input_box', timeout=timeout, poll_frequency=0.1):
                self.logger.info("Chat window closed successfully via click outside")
                return True

        for attempt in range(max_back_attempts):
            if not self.is_chat_window_open():
                break
            self.logger.warning(
                f"Input box still visible after click outside, pressing back to close chat window (attempt {attempt + 1}/{max_back_attempts})"
            )
            self.key_actions.press_back()
            if hasattr(self.element_finder, 'wait_for_element_disappear'):
                if self.element_finder.wait_for_element_disappear('input_box', timeout=timeout, poll_frequency=0.1):
                    self.logger.info(f"Chat window closed successfully via press_back (attempt {attempt + 1})")
                    return True

        closed = not self.is_chat_window_open()
        if not closed:
            self.logger.error("Failed to close chat window after click and press_back attempts")
        return closed

    def send_message(self, message):
        """Send a room message through the low-level Soul UI primitive.

        Business code should use ``MessageDispatch`` so routing and suppression
        are applied consistently.
        """

        self.key_actions.switch_to_app()

        # 预防性检查：若聊天窗口已打开，先将其关闭以保证 input_box_entry 能被正常定位
        if self.is_chat_window_open():
            self.logger.warning("Chat window was already open at start of send_message, closing it first")
            self.ensure_chat_window_closed()

        # Click on the input box entry first
        input_box_entry = self.element_finder.wait_for_element_clickable('input_box_entry')
        if not input_box_entry:
            self.logger.error(f'cannot find input box entry, might be in loading')
            return {'error': 'cannot find input box entry, might be in loading'}
        go_back = self.element_finder.try_find_element('go_back_1', log=False)
        if go_back:
            go_back.click()
            self.logger.error("Clicked go back button, might be in chat screen")
            return {'error': 'cannot find input box entry, might be in chat screen'}
        input_box_entry.click()
        # self.logger.info("Clicked input box entry")

        # Now find and interact with the actual input box
        input_box = self.element_finder.wait_for_element_clickable('input_box')
        if not input_box:
            self.logger.error(f'cannot find input box, might be in chat screen')
            self.ensure_chat_window_closed()
            return {
                'error': 'Failed to find input box',
            }

        try:
            if len(message) > 0:
                input_box.send_keys(message)
                self.logger.info(f"Entered message: {message}")

                # click send button
                send_button = self.element_finder.wait_for_element_clickable('button_send')
                if not send_button:
                    self.logger.error(f'cannot find send button')
                    return {
                        'error': 'Failed to find send button',
                    }

                send_button.click()
                # self.logger.info("Clicked send button")
        finally:
            self.ensure_chat_window_closed(input_element=input_box)

    def grab_mic_and_confirm(self):
        """Wait for the grab mic button and confirm the action"""
        try:
            # Wait for the grab mic button to be clickable
            grab_mic_button = self.element_finder.wait_for_element_clickable('grab_mic')
            grab_mic_button.click()

            # Wait for the confirmation dialog to appear
            confirm_button = self.element_finder.wait_for_element_clickable('confirm_mic')
            confirm_button.click()

        except Exception as e:
            self.logger.error(f"Error grabbing mic: {str(e)}")

    def is_on_seat(self) -> bool:
        """是否已在麦位：界面出现上麦/抢麦入口即表示尚未就座。"""
        return self.element_finder.try_find_element('grab_mic', log=False) is None

    def ensure_on_seat(self) -> bool:
        """确保账号已在麦位；未上麦时先抢麦并等待就座。

        开麦前必须先就座：不在麦位时界面只提供抢麦入口，直接点击开麦按钮
        会失败或抛错。

        Returns:
            bool: True 表示当前已在麦位（含本次抢麦成功），False 表示未能就座
        """
        if self.is_on_seat():
            return True

        self.logger.info("Not on seat, grabbing mic to take a seat")
        self.grab_mic_and_confirm()
        seated = self.element_finder.wait_for_element_disappear(
            'grab_mic', timeout=self.SEAT_SETTLE_TIMEOUT
        )
        if not seated:
            self.logger.error("Failed to grab mic: still not seated")
        return seated

    def ensure_mic_active(self):
        """Ensure the microphone is active"""
        try:
            self.key_actions.switch_to_app()

            if not self.is_on_seat():
                self.logger.info("Grab mic button found, grabbing mic...")
                self.grab_mic_and_confirm()
            else:
                self.logger.info("Already on mic, checking toggle mic status...")
                # Check the toggle mic button
                toggle_mic_button = self.element_finder.wait_for_element_clickable('toggle_mic')

                if not toggle_mic_button:
                    self.logger.error("Toggle mic button not found")
                    return

                desc = self.element_finder.try_get_attribute(toggle_mic_button, 'content-desc')
                if desc == "开麦按钮":  # If we see "开麦按钮", mic is currently off
                    self.logger.info("Mic is off, turning it on...")
                    toggle_mic_button.click()
                    self.logger.info("Clicked toggle mic button to turn on mic")

        except Exception as e:
            self.logger.error(f"Error ensuring mic is active: {str(e)}")
