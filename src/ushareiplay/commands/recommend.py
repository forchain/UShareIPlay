from ushareiplay.core.base_command import BaseCommand


class RecommendCommand(BaseCommand):
    """`:recommend` —— 薄适配器，逻辑全在 `RoomProfileManager`（#393）。

    参数解析与「回复长什么样」留在命令这一层（config.yaml 的 `:recommend` 模板
    是 `派对推荐已设置为: {status}`，因此这里必须交出 `status` 键）；抽屉会话、
    推荐分发的真实状态读写、以及建房/回房时的全量纠偏都在房间档案模块内。

    与话题/公告/房名三条纵切**形状不同**：推荐分发没有冷却，因此这里不像那三条
    「先排队、回复立刻给、真正写入等下一次心跳」—— `set_recommendation` 当场
    就写完，回复在写入之后返回。

    `handler_attr` 与 `error_message` 保持原样（后者沿用基类的
    `'Failed to process command: {error}'`），模板因此不需要改。
    """

    handler_attr = 'soul_handler'

    async def do_process(self, message_info, parameters):
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}

        profile = self.room_profile_manager
        current_status = profile.room_state.recommendation_enabled

        if not parameters:
            # Toggle current state (if None or True -> False, if False -> True)
            target_state = not current_status if current_status is not None else False
        else:
            arg = str(parameters[0]).strip().lower()
            if arg in ('on', 'open', '1', '开启', '开放', '所有人'):
                target_state = True
            elif arg in ('off', 'close', '0', '关闭', '关闭推荐分发'):
                target_state = False
            else:
                return {'error': f'未知参数 "{parameters[0]}", 请使用 on/off 或 开启/关闭'}

        result = profile.set_recommendation(target_state)
        if 'error' in result:
            return result

        return {'status': '开放' if target_state else '关闭'}
