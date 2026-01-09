import asyncio
import time

from ..core.singleton import Singleton
from ..models.message_info import MessageInfo


class RecoveryManager(Singleton):
    """异常检测和恢复管理器，用于检测和处理各种异常情况"""

    def __init__(self):
        # 获取 SoulHandler 单例实例
        from ..handlers.soul_handler import SoulHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger
        self._party_manager = None  # 延迟初始化，避免循环依赖

    @property
    def party_manager(self):
        """Lazy load PartyManager instance"""
        if self._party_manager is None:
            from ..managers.party_manager import PartyManager
            self._party_manager = PartyManager.instance()
        return self._party_manager

    def _set_default_notice(self):
        """设置默认notice（使用NoticeManager）"""
        try:
            from .notice_manager import NoticeManager
            notice_manager = NoticeManager.instance()
            result = notice_manager.set_default_notice()

            if 'success' in result:
                self.logger.info("默认notice设置成功")
                return True
            else:
                self.logger.warning(f"默认notice设置失败: {result.get('error', 'Unknown error')}")
                return False

        except Exception as e:
            self.logger.error(f"设置默认notice时出错: {str(e)}")
            return False

    def _seat_owner_after_party_creation(self):
        """Seat the owner after party creation/restoration"""
        try:
            time.sleep(1.5)  # Wait for party UI to stabilize

            from ..managers.seat_manager import seat_manager
            self.logger.info("Attempting to seat owner after party creation")
            result = seat_manager.seating.find_owner_seat()

            if 'success' in result:
                self.logger.info("Owner successfully seated")
                return True
            else:
                self.logger.warning(f"Failed to seat owner: {result.get('error', 'Unknown error')}")
                return False
        except Exception as e:
            self.logger.error(f"Error seating owner: {str(e)}")
            return False

    def _execute_radio_after_creation(self):
        """创建房间后执行 radio 命令"""
        try:

            # 创建 MessageInfo 对象
            message_info = MessageInfo(
                content="radio",
                nickname="Joyer"
            )

            async def _run_radio():
                try:
                    # 执行 radio 命令（默认 collection，参数为空列表）
                    await self.handler.controller.radio_command.process(message_info, [])
                    self.logger.info("Radio command executed after party creation")
                except Exception as e:
                    self.logger.error(
                        f"Radio command task failed after party creation: {str(e)}"
                    )

            # 当前 check_and_recover 是在已有事件循环中被调用的，这里不能再用 asyncio.run
            loop = asyncio.get_running_loop()
            loop.create_task(_run_radio())
        except Exception as e:
            self.logger.error(f"Failed to execute radio command after party creation: {str(e)}")

    def is_normal_state(self) -> bool:
        """
        检测是否处于正常状态
        最快速的方法就是检测输入框是否存在
        """
        try:
            # 从 InfoManager 获取房间ID
            from .info_manager import InfoManager
            info_manager = InfoManager.instance()
            room_id_text = info_manager.room_id

            if room_id_text is None:
                return False

            if not room_id_text.startswith("FM"):
                self.logger.warning(f"Room ID:{room_id_text} does not start with FM, skip")
                return True

            party_id = self.handler.config.get('default_party_id')
            return room_id_text == party_id
        except Exception as e:
            self.logger.debug(f"检测正常状态时出错: {str(e)}")
            return False

    def handle_join_party(self) -> bool:
        """
        处理其他可能的异常情况
        返回True表示执行了操作，False表示没有找到需要处理的情况
        """

        # 检测是否在首页（非派对页面）
        try:
            planet_tab = self.handler.try_find_element_plus('planet_tab', log=False)
            if not planet_tab:
                return False
            self.logger.info("发现首页，尝试进入派对")
            planet_tab.click()

            party_hall_entry = self.handler.wait_for_element_clickable_plus('party_hall_entry')
            if not party_hall_entry:
                self.logger.warning("未找到派对大厅入口")
                return False
            party_hall_entry.click()
            self.logger.info("Clicked party hall entry")

            key, element = self.handler.wait_for_any_element_plus(
                ['party_back', 'search_entry'])
            if not element:
                self.logger.warning("未找到派对入口")
                return False

            if key == 'party_back':
                element.click()
                self.logger.info("Clicked back to party")
                return True

            if key == 'search_entry':
                search_entry = element
                search_entry.click()
                self.logger.info("Clicked search entry")
                search_box = self.handler.wait_for_element_plus('search_box')
                if not search_box:
                    self.logger.warning("未找到搜索框")
                    return False
                party_id = self.handler.party_id or self.handler.config['default_party_id']
                search_box.send_keys(party_id)
                self.logger.info(f"Entered party ID: {party_id}")
                search_button = self.handler.wait_for_element_plus('search_button')
                if not search_button:
                    self.logger.warning("未找到搜索按钮")
                    return False
                search_button.click()
                self.logger.info("Clicked search button")

                room_card = self.handler.wait_for_element_plus('room_card')
                if not room_card:
                    self.logger.warning("未找到派对房间")
                    return False
                party_online = self.handler.try_find_element_plus('party_online')
                if party_online:
                    party_online.click()
                    self.logger.info("Clicked party online")
                    return True
                else:
                    self.logger.warning("派对关闭了")
                    search_back = self.handler.wait_for_element_plus('search_back')
                    search_back.click()
                    self.logger.info("Clicked search back")

            key, element = self.handler.wait_for_any_element_plus(
                ['create_party_entry', 'create_room_entry'])
            if not element:
                self.logger.warning("未找到派对入口")
                return False
            element.click()
            self.logger.info("Clicked create party entry")

            key, element = self.handler.wait_for_any_element_plus(
                ['confirm_party', 'restore_party', 'create_party_button'])
            if not element:
                self.logger.warning("未找到派对创建或恢复按钮")

            if key == 'create_party_button':
                element.click()
                self.logger.info("Clicked create party button")

                # 派对创建成功后，重置派对时间
                self.party_manager.reset_party_time()

                # 派对创建成功后，设置默认notice
                self.logger.info("派对创建成功，准备设置默认notice")
                if self._set_default_notice():
                    self.logger.info("默认notice设置成功")
                else:
                    self.logger.warning("默认notice设置失败")

                # Seat the owner after party creation
                self._seat_owner_after_party_creation()

                return True

            if key == 'confirm_party':
                element.click()
                self.logger.info("Clicked confirm party button")
                key, element = self.handler.wait_for_any_element_plus(['create_party_button', 'room_id'])
                if not element:
                    self.logger.warning("未找到派对创建或恢复按钮")
                    return False
                if key == 'create_party_button':
                    element.click()
                    self.logger.info("Clicked create party button")

                    # 派对创建成功后，重置派对时间
                    self.party_manager.reset_party_time()

                    # 派对创建成功后，设置默认notice
                    self.logger.info("派对创建成功，准备设置默认notice")
                    if self._set_default_notice():
                        self.logger.info("默认notice设置成功")
                    else:
                        self.logger.warning("默认notice设置失败")

                    # Seat the owner after party creation
                    self._seat_owner_after_party_creation()

                return True

            element.click()
            self.logger.info("Clicked restore party button")
            key, element = self.handler.wait_for_any_element_plus(['confirm_party', 'room_id'])
            if key == 'confirm_party':
                # confirm_party is found but not clickable - wait for it to become clickable
                confirm_party = self.handler.wait_for_element_clickable_plus('confirm_party')
                if not confirm_party:
                    self.logger.error("confirm party button not found")
                    return False
                confirm_party.click()
                self.logger.info("Clicked confirm party button")
                key, element = self.handler.wait_for_any_element_plus(['create_party_button', 'room_id'])
                if not element:
                    self.logger.warning("未找到派对创建或恢复按钮")
                    return False
                if key == 'create_party_button':
                    element.click()
                    self.logger.info("Clicked create party button")

            # 派对创建成功后，重置派对时间
            self.party_manager.reset_party_time()

            # 派对创建成功后，设置默认notice
            self.logger.info("派对创建成功，准备设置默认notice")
            if self._set_default_notice():
                self.logger.info("默认notice设置成功")
            else:
                self.logger.warning("默认notice设置失败")

            # Seat the owner after party creation
            self._seat_owner_after_party_creation()

            # 执行 radio 命令
            self._execute_radio_after_creation()

            return True


        except Exception as e:
            self.logger.debug(f"检测首页时出错: {str(e)}")

        return False
