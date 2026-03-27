from ushareiplay.core.base_command import BaseCommand


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
            mode_names = {0: '顺序播放', 1: '单曲循环', -1: '随机播放'}

            def key_to_mode(key: str) -> int:
                if key == 'play_mode_list':
                    return 0
                if key == 'play_mode_single':
                    return 1
                if key == 'play_mode_random':
                    return -1
                raise ValueError(f"Unknown play mode key: {key}")

            def log_step(step: str, **kwargs):
                kv = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
                self.handler.logger.info(f"[MODE_TEST][{step}] {kv}".strip())

            # 0. 先切换到音乐App
            switched = self.handler.switch_to_app()
            if not switched:
                self.handler.logger.info("无法切换到音乐App")
                return {
                    'error': '无法切换到音乐App，稍后重试'
                }

            self.handler.press_back()

            # 1. 尝试查找当前界面状态
            # - playing_bar: 在非播放页但底部有播放导航条，需要先点它进入播放页
            # - play_mode_*: 已在播放页，可直接切换（不再依赖 playlist_entry 展开控制区）
            element_keys = [
                'playing_bar',
                'play_mode_list',
                'play_mode_single',
                'play_mode_random',
            ]
            found_element_key, found_element = self.handler.wait_for_any_element_plus(element_keys)

            if not found_element_key or not found_element:
                self.handler.logger.info("未找到播放模式相关元素，说明现在没有播放音乐")
                return {
                    'error': '现在没有播放音乐，无法切换模式'
                }

            log_step("Step0", found_key=found_element_key)

            # 2. 如果在非播放页：先点底部 Playing Bar 进入播放页
            if found_element_key == 'playing_bar':
                self.handler.logger.info("找到 playing_bar，点击进入播放页")
                if not self.handler.click_element_at(found_element):
                    return {
                        'error': 'FAIL: 点击 playing_bar 进入播放页失败'
                    }

                # 进入播放页后，再等待播放模式按钮出现
                mode_element_keys = ['play_mode_list', 'play_mode_single', 'play_mode_random']
                found_element_key, found_element = self.handler.wait_for_any_element_plus(mode_element_keys)
                log_step("Step1", after_playing_bar_found_key=found_element_key)

                if not found_element_key or not found_element:
                    return {
                        'error': 'FAIL: 点击 playing_bar 后仍未找到播放模式控制元素'
                    }

            # 3. 检查是否找到播放模式元素
            current_mode_element = found_element
            current_mode = key_to_mode(found_element_key)

            log_step("Step2", current_mode=mode_names[current_mode], target_mode=mode_names[target_mode])

            # 如果已经是目标模式，直接返回
            if current_mode == target_mode:
                log_step("Result", status="PASS", mode=mode_names[target_mode], reason="already_target")
                return {
                    'success': True,
                    'mode': mode_names[target_mode],
                    'message': f'已经是{mode_names[target_mode]}模式'
                }

            # 5. 尝试切换到目标模式（最多切换两次）
            for attempt in range(2):
                log_step(
                    "Step3",
                    attempt=attempt + 1,
                    before_click_mode=mode_names[current_mode],
                    target_mode=mode_names[target_mode],
                )
                if not self.handler.click_element_at(current_mode_element):
                    self.handler.logger.warning("click_element_at 返回 False，继续下一次重试")
                    continue

                # 重新检查当前模式
                mode_element_keys = ['play_mode_list', 'play_mode_single', 'play_mode_random']
                found_element_key, found_element = self.handler.wait_for_any_element_plus(mode_element_keys)

                if not found_element_key or not found_element:
                    self.handler.logger.warning("切换后未找到播放模式元素")
                    continue

                # 确定当前模式
                current_mode_element = found_element
                current_mode = key_to_mode(found_element_key)

                log_step("Step3", after_click_current_mode=mode_names[current_mode])

                # 检查是否达到目标模式
                if current_mode == target_mode:
                    log_step("Result", status="PASS", mode=mode_names[target_mode], attempt=attempt + 1)
                    return {
                        'success': True,
                        'mode': mode_names[target_mode],
                        'message': f'成功切换到{mode_names[target_mode]}模式'
                    }

            # 如果两次尝试后仍未达到目标模式，报错
            self.handler.logger.warning("经过两次切换仍未达到目标模式")
            log_step(
                "Result",
                status="FAIL",
                target_mode=mode_names[target_mode],
                actual_mode=mode_names[current_mode],
                reason="not_reached_after_attempts",
            )
            return {
                'error': f'FAIL: 无法切换到目标模式，请检查播放状态（target={mode_names[target_mode]}, actual={mode_names[current_mode]}）'
            }

        except Exception as e:
            self.handler.log_error(f"切换播放模式时发生错误: {str(e)}")
            return {
                'error': f'切换模式失败: {str(e)}'
            }
