from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.recommendation_manager import RecommendationManager


class RecommendCommand(BaseCommand):
    handler_attr = 'soul_handler'

    async def do_process(self, message_info, parameters):
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}

        rec_manager = RecommendationManager.instance()
        current_status = rec_manager.room_state.recommendation_enabled

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

        # 打开/关闭窗口归 RoomInfoWindow（原先这里是第五份手写打开副本）
        from ushareiplay.managers.room_info_window import RoomInfoWindow
        window = RoomInfoWindow.instance()
        open_error = window.ensure_open(error_message='Failed to find room title')
        if open_error:
            return open_error

        update_res = rec_manager.update_recommendation_ui(target_state)
        window.close_with_back()

        if 'error' in update_res:
            return update_res

        return {'status': '开放' if target_state else '关闭'}
