"""`:mic` 入站适配器：决定目标状态，交给 `ToggleMic`。"""

from ushareiplay.core.base_command import BaseCommand


class MicCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '{error}'

    def __init__(self, controller):
        super().__init__(controller)
        self.toggle_mic = controller.toggle_mic
        # 座位状态经注入的 callable 读取（不 import 座位内部实现）。
        self.seat_presence = self.soul_handler.is_on_seat

    async def do_process(self, message_info, parameters):
        """Process mic command
        Args:
            message_info: MessageInfo object
            parameters: List of parameters
        Returns:
            dict: Result with success or error
        """
        if not parameters:
            # 抢麦会随座位自动开麦，因此不在麦位时裸 :mic 等同于开麦，
            # 而不是刚就座就把麦克风关掉。
            if not self.seat_presence():
                return self.toggle_mic.set(True)
            return self.toggle_mic.toggle()

        action = parameters[0]
        if action not in ['0', '1']:
            return {'error': 'Invalid parameter. Usage: :mic 0/1'}

        return self.toggle_mic.set(action == '1')
