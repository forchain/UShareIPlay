from ushareiplay.core.base_command import BaseCommand


class RecommendCommand(BaseCommand):
    """`:recommend` —— 薄适配器，逻辑全在 `RoomProfileManager`（#456）。

    参数解析与「回复长什么样」留在命令这一层（config.yaml 的 `:recommend` 模板
    是 `派对推荐已设置为: {status}`，因此这里必须交出 `status` 键）；设置面板的
    开关、翻页找状态项、二级弹窗与真实状态读写都在房间档案模块内。

    推荐分发**没有冷却**：一次 `:recommend` 当场就写完 UI，回复在写入之后返回。
    """

    handler_attr = 'soul_handler'

    #: 目标状态 -> 用户可读文案。config 的 `:recommend` 模板消费 `status`。
    STATUS_TEXT = {True: '开放', False: '关闭'}
    #: 开启 / 关闭的中英文与 UI 原文别名。
    ENABLE_ALIASES = ('on', 'open', '1', '开启', '开放', '所有人')
    DISABLE_ALIASES = ('off', 'close', '0', '关闭', '关闭推荐分发')

    async def do_process(self, message_info, parameters):
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}

        profile = self.room_profile_manager
        current_status = profile.recommendation_enabled

        if parameters:
            target_state = self._parse_target(str(parameters[0]).strip().lower())
            if target_state is None:
                return {
                    'error': f'未知参数 "{parameters[0]}", 请使用 on/off 或 开启/关闭'
                }
        else:
            # 无参数：当前开着就关，当前关着（或还不知道）就开。
            target_state = not current_status if current_status is not None else True

        result = profile.set_recommendation(target_state)
        if 'error' in result:
            return result

        enabled = result.get('recommendation_enabled', target_state)
        return {'status': self.STATUS_TEXT[bool(enabled)]}

    def _parse_target(self, argument: str):
        """参数 -> 目标状态；不认识返回 None。"""
        if argument in self.ENABLE_ALIASES:
            return True
        if argument in self.DISABLE_ALIASES:
            return False
        return None
