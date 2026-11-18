from ushareiplay.core.base_command import BaseCommand


class NoticeCommand(BaseCommand):
    """公告命令 —— 只解析参数、拼装回复，业务全在 `RoomProfileManager` 里。

    参数拼接与「回复长什么样」留在命令这一层（config.yaml 的 `:notice` 模板
    是 `Change notice to {notice}`，因此这里必须交出 `notice` 键）；排队、
    15 分钟冷却、写抽屉、以及写成功后的公屏播报都在房间档案模块内。
    `handler_attr` 与 `error_message` 保持原样，模板因此不需要改。

    与话题那条纵切同形：**这一层不碰 UI**。用户下完 `:notice` 立刻收到
    「Change notice to ...」，真正写入由 `update()` 的心跳在预算允许时完成。
    """

    handler_attr = 'soul_handler'
    error_message = 'Failed to process notice command: {error}'

    async def do_process(self, message_info, parameters):
        """安排一条公告：参数拼接交给命令，排队与冷却交给房间档案模块。"""
        if not parameters:
            return {'error': 'Missing notice parameter'}

        new_notice = ' '.join(parameters)
        result = self.room_profile_manager.set_notice(new_notice)

        if 'cooldown' in result:
            remaining_minutes = result.get('remaining_minutes', 0)
            return {'notice': f'{new_notice}. Notice will update in {remaining_minutes} minutes'}

        if 'success' in result:
            return {'notice': f'{new_notice}'}

        error_msg = result.get('error', 'Unknown error')
        self.handler.logger.error(f'Failed to update notice: {error_msg}')
        return {'error': f'Failed to update notice: {error_msg}'}

    def update(self):
        """心跳：冷却到期且排队的公告由 `RoomProfileManager` 写进抽屉。

        返回值一律忽略 —— 写成功后往公屏播报的那句话由房间档案模块负责，
        这里没有需要回给用户的东西。
        """
        self.room_profile_manager.update_notice()