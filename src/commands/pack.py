import traceback

from ..core.base_command import BaseCommand


def create_command(controller):
    pack_command = PackCommand(controller)
    controller.pack_command = pack_command
    return pack_command


command = None


class PackCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.auto_mode = False
        self.previous_count = 0  # Track previous user count

    async def process(self, message_info, parameters):
        """Process pack command to open luck pack"""
        try:
            # Check if user has relation tag (is a close friend)
            if not message_info.relation_tag and message_info.nickname != 'Joyer':
                return {'error': 'Only close friends can open luck packs'}

            self.auto_mode = False  # Manual mode
            return self.open_luck_pack()  # Manual mode doesn't need user count
        except Exception as e:
            self.handler.log_error(f"Error processing pack command: {str(e)}")
            return {'error': 'Failed to open luck pack'}

    def update(self):
        """Check room count and auto open pack if needed"""
        try:
            # 从 InfoManager 获取在线人数
            from ..managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            count = info_manager.user_count
            
            if count is None:
                return

            # Only check if count has changed
            if count != self.previous_count:
                self.previous_count = count  # Update previous count
                if count > 5:
                    self.auto_mode = True  # Auto mode
                    self.open_luck_pack(user_count=count)  # Pass user count as parameter

        except Exception as e:
            self.handler.log_error(f"Error in pack update: {traceback.format_exc()}")

    def open_luck_pack(self, user_count=None):
        """Open luck pack if available
        Args:
            user_count: Optional[int], current user count in room
        """
        try:
            # Find luck pack button
            luck_pack = self.handler.try_find_element_plus('luck_pack', log=False)
            if not luck_pack:
                return {'error': 'No luck pack available'}

            # Check if text contains "奖励"
            pack_text = luck_pack.text
            if "奖励" not in pack_text:
                self.handler.logger.info(f"Luck pack text '{pack_text}' does not contain '奖励'")
                return {'error': 'No luck pack available'}

            # Click luck pack button to show list
            luck_pack.click()
            self.handler.logger.info("Clicked luck pack button")

            # Find and click luck item
            luck_item = self.handler.wait_for_element_clickable_plus('luck_item')
            if not luck_item:
                self.handler.logger.error("Failed to find luck item")
                return {'error': 'Failed to find luck item'}

            # In auto mode, check pack level based on user count
            if self.auto_mode and user_count is not None:
                item_text = luck_item.text
                # If less than 10 people, only allow low/medium level packs
                if user_count <= 10 and not (
                        "初级" in item_text or "中级" in item_text or "一级" in item_text or "二级" in item_text):
                    self.handler.logger.info(f"Skipping high level pack with {user_count} users: {item_text}")
                    self.handler.press_back()
                    return {'error': 'Skipping high level pack (not enough users)'}

            luck_item.click()
            self.handler.logger.info("Selected luck item")

            # Find and click use pack button
            use_pack = self.handler.wait_for_element_clickable_plus('use_pack')
            if not use_pack:
                self.handler.logger.error("Failed to find use pack button")
                return {'error': 'Failed to find use pack button'}

            use_pack.click()
            self.handler.logger.info(f"Used luck pack in {'auto' if self.auto_mode else 'manual'} mode")

            return {'item': luck_item.text}

        except Exception as e:
            self.handler.log_error(f"Error opening luck pack: {traceback.format_exc()}")
            return {'error': 'Failed to open luck pack'}
