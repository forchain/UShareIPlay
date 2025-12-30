from ..core.base_command import BaseCommand


def create_command(controller):
    accompaniment_command = AccompanimentCommand(controller)
    controller.accompaniment_command = accompaniment_command
    return accompaniment_command


command = None


class AccompanimentCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    async def process(self, message_info, parameters):
        # Get parameter
        if len(parameters) == 0:
            return {
                'error': 'Missing parameter (on:1, off:0) for accompaniment command'
            }

        enable = parameters[0] == '1'
        # Toggle accompaniment mode
        return self.toggle_accompaniment(enable)

    def toggle_accompaniment(self, enable):
        """Toggle accompaniment mode
        Args:
            enable: bool, True to enable, False to disable
        Returns:
            dict: {'enabled': 'on'/'off'}
        """
        if not self.handler.switch_to_app():
            return {'error': 'Failed to switch to QQ Music app'}
        self.handler.logger.info("Switched to QQ Music app")

        self.handler.press_back()
        # 1. 查找四个控件中的任意一个，找不到说明没有在播放
        found_key, found_element = self.handler.wait_for_any_element_plus([
            'accompaniment_text_off', 'accompaniment_text_on', 'playing_bar', 'more_entry'
        ])

        if not found_element:
            self.handler.logger.warning("No music playing detected")
            return {'error': 'No music playing, cannot toggle accompaniment mode'}

        # 2. 判断找到的是哪种元素并处理
        if found_key == 'playing_bar':
            # 找到播放条，需要进入播放页面
            self.handler.logger.info("Found playing bar, clicking to enter playing page")
            if not self.handler.click_element_at(found_element):
                return {'error': 'Failed to click playing bar'}

            found_key, found_element = self.handler.wait_for_any_element_plus([
                'accompaniment_text_off', 'accompaniment_text_on', 'more_entry'
            ])

            if not found_element:
                return {'error': 'Failed to find accompaniment controls after entering playing page'}

        # 3. 如果找到的是accompaniment_switch，说明此前还没激活过伴唱模式
        if found_key == 'more_entry':

            accompaniment_switch = self.handler.try_find_element_plus('accompaniment_switch')
            # if disabled, return
            if accompaniment_switch and accompaniment_switch.get_attribute('enabled') == 'false':
                return {'error': 'Accompaniment mode is disabled'}

            self.handler.logger.info("Found accompaniment more menu entry, activating accompaniment mode")
            if not self.handler.click_element_at(found_element):
                return {'error': 'Failed to click accompaniment switch'}

            # 查找伴唱菜单
            button_key, found_button = self.handler.scroll_container_until_element('accompaniment_menu',
                                                                                   'menu_container')
            if found_button is None:
                return {'error': 'Failed to find accompaniment menu'}
            found_button.click()
            self.handler.logger.info("Clicked accompaniment menu")

            # 查找伴唱状态按钮
            button_key, found_button = self.handler.wait_for_any_element_plus([
                'accompaniment_button_on', 'accompaniment_button_off'
            ])

            if not found_button:
                return {'error': 'Failed to find accompaniment menu'}

            # 根据找到的按钮类型确定当前状态
            current_state = button_key == 'accompaniment_button_on'  # True表示已开启

            if enable != current_state:
                # 需要切换状态，直接点击找到的按钮
                if not self.handler.click_element_at(found_button):
                    return {'error': 'Failed to toggle accompaniment state'}
                self.handler.logger.info(f"Toggled accompaniment state to {'on' if enable else 'off'}")
            else:
                self.handler.logger.info(f"Accompaniment state already {'on' if enable else 'off'}, no action needed")
            self.handler.press_back()

        # 4. 如果找到的是accompaniment_text_off或accompaniment_text_on，说明已经开启过伴奏模式
        else:
            # 根据找到的文本类型确定当前状态
            current_state = found_key == 'accompaniment_text_on'  # True表示已开启

            if enable != current_state:
                # 需要切换状态，直接点击找到的元素
                if not self.handler.click_element_at(found_element):
                    return {'error': f"Failed to {'enable' if enable else 'disable'} accompaniment mode"}
                self.handler.logger.info(f"{'Enabled' if enable else 'Disabled'} accompaniment mode")
            else:
                self.handler.logger.info(f"Accompaniment mode already {'on' if enable else 'off'}, no action needed")

        return {'enabled': 'on' if enable else 'off'}
