from ..core.base_command import BaseCommand


def create_command(controller):
    mode_command = ModeCommand(controller)
    controller.mode_command = mode_command
    return mode_command


command = None


class ModeCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.music_handler

    async def process(self, message_info, parameters):
        if len(parameters) == 0:
            return {
                'error': 'Missing mode parameter'
            }
        try:
            mode = int(parameters[0])
            if mode not in [0, 1, -1]:
                raise ValueError

            # 直接实现切换模式逻辑
            result = await self._change_play_mode_direct(mode)
            return result
        except ValueError:
            return {
                'error': 'Invalid mode parameter, must be 0, 1 or -1'
            }
        except Exception as e:
            self.handler.log_error(f"Error in mode command: {str(e)}")
            return {
                'error': f'Mode change failed: {str(e)}'
            }

    async def _change_play_mode_direct(self, target_mode):
        """直接实现切换模式功能"""
        try:
            # 0. 先切换到音乐App
            switched = self.handler.switch_to_app()
            if not switched:
                self.handler.logger.info("无法切换到音乐App")
                return {
                    'error': '无法切换到音乐App，稍后重试'
                }

            self.handler.press_back()

            # 1. 尝试查找四个元素中的任意一个
            element_keys = ['playlist_entry', 'play_mode_list', 'play_mode_single', 'play_mode_random']
            found_element_key, found_element = self.handler.wait_for_any_element_plus(element_keys)

            if not found_element_key or not found_element:
                self.handler.logger.info("未找到播放模式相关元素，说明现在没有播放音乐")
                return {
                    'error': '现在没有播放音乐，无法切换模式'
                }

            # 2. 如果找到playlist_entry，说明列表没有显示，先点击
            if found_element_key == 'playlist_entry':
                self.handler.logger.info("找到播放列表入口，先点击显示播放列表")
                found_element.click()

                # 重新查找播放模式元素
                mode_element_keys = ['play_mode_list', 'play_mode_single', 'play_mode_random']
                found_element_key, found_element = self.handler.wait_for_any_element_plus(mode_element_keys)

                if not found_element_key or not found_element:
                    self.handler.logger.info("点击播放列表后仍未找到播放模式元素")
                    return {
                        'error': '无法找到播放模式控制元素'
                    }

            # 3. 检查是否找到播放模式元素
            mode_names = {0: '顺序播放', 1: '单曲循环', -1: '随机播放'}
            current_mode_element = found_element
            if found_element_key == 'play_mode_list':
                current_mode = 0  # 顺序播放
            elif found_element_key == 'play_mode_single':
                current_mode = 1  # 单曲循环
            elif found_element_key == 'play_mode_random':
                current_mode = -1  # 随机播放
            else:
                self.handler.logger.info("未找到有效的播放模式元素")
                return {
                    'error': '无法找到播放模式控制元素'
                }

            self.handler.logger.info(f"当前播放模式: {mode_names[current_mode]}, 目标模式: {mode_names[target_mode]}")

            # 如果已经是目标模式，直接返回
            if current_mode == target_mode:
                return {
                    'success': True,
                    'mode': mode_names[target_mode],
                    'message': f'已经是{mode_names[target_mode]}模式'
                }

            # 4. 尝试切换到目标模式（最多切换两次）
            for attempt in range(2):
                self.handler.logger.info(f"第{attempt + 1}次尝试切换模式")
                current_mode_element.click()

                # 重新检查当前模式
                mode_element_keys = ['play_mode_list', 'play_mode_single', 'play_mode_random']
                found_element_key, found_element = self.handler.wait_for_any_element_plus(mode_element_keys)

                if not found_element_key or not found_element:
                    self.handler.logger.warning("切换后未找到播放模式元素")
                    continue

                # 确定当前模式
                current_mode_element = found_element
                if found_element_key == 'play_mode_list':
                    current_mode = 0
                elif found_element_key == 'play_mode_single':
                    current_mode = 1
                elif found_element_key == 'play_mode_random':
                    current_mode = -1

                self.handler.logger.info(f"切换后当前模式: {mode_names[current_mode]}")

                # 检查是否达到目标模式
                if current_mode == target_mode:
                    mode_names = {0: '顺序播放', 1: '单曲循环', -1: '随机播放'}
                    return {
                        'success': True,
                        'mode': mode_names[target_mode],
                        'message': f'成功切换到{mode_names[target_mode]}模式'
                    }

            # 如果两次尝试后仍未达到目标模式，报错
            self.handler.logger.warning("经过两次切换仍未达到目标模式")
            return {
                'error': '无法切换到目标模式，请检查播放状态'
            }

        except Exception as e:
            self.handler.log_error(f"切换播放模式时发生错误: {str(e)}")
            return {
                'error': f'切换模式失败: {str(e)}'
            }
