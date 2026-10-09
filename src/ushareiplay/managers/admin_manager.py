import logging
from typing import Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.recovery_manager import RecoveryManager
from ushareiplay.managers.user_manager import UserManager


class AdminManager(Singleton):
    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._room_admins: set[str] = set()

    def is_room_admin(self, username: str) -> bool:
        """检查用户是否为房间管理员"""
        if not username:
            return False
        return username in self._room_admins

    def get_room_admins(self) -> set[str]:
        """获取当前活跃房间管理员集合（副本）"""
        return set(self._room_admins)

    def add_room_admin(self, username: str) -> None:
        """添加用户至房间管理员列表"""
        if username:
            self._room_admins.add(username)

    def remove_room_admin(self, username: str) -> None:
        """从房间管理员列表中移除用户"""
        self._room_admins.discard(username)

    def clear_room_admins(self) -> None:
        """清空房间管理员列表"""
        self._room_admins.clear()

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("AdminManager")
        return self._logger

    async def manage_admin(self, enable: bool, target_nickname: str):
        """
        管理管理员状态：在在线列表中打开目标用户资料页，再执行邀请/解除管理。

        Args:
            enable: True 邀请为管理员，False 解除管理员
            target_nickname: 被操作的用户昵称（在在线列表中查找并打开其资料页）

        Returns:
            dict: 成功含 user/action，失败含 error/user
        """
        # 在线列表里显示的是 Soul UI 的可见名字（分身名），传入主账号名会找不到人，
        # 因此先把目标解析成房间里当前可见的那个名字。
        try:
            visible_nickname = await InfoManager.instance().resolve_visible_username(target_nickname)
        except Exception:
            visible_nickname = target_nickname

        user_manager = UserManager.instance()
        open_result = await user_manager.open_user_profile(visible_nickname)
        if 'error' in open_result:
            return open_result
        # 房间管理员按 UI 名字记账：麦位观测与 :info 都用 slot.username（分身名）比对。
        target_nickname = open_result.get('user') or visible_nickname

        manager_invite = self.handler.element_finder.wait_for_element_clickable('manager_invite')
        if not manager_invite:
            await self._close_profile(open_result)
            return {'error': 'Failed to find manager invite button', 'user': target_nickname}

        current_text = manager_invite.text
        if enable:
            if current_text == "解除管理":
                self.add_room_admin(target_nickname)
                await self._close_profile(open_result)
                return {'error': '你已经是管理员了', 'user': target_nickname}
        else:
            if current_text == "管理邀请":
                self.remove_room_admin(target_nickname)
                await self._close_profile(open_result)
                return {'error': '你还不是管理员', 'user': target_nickname}

        manager_invite.click()
        self.logger.info("Clicked manager invite button")

        if enable:
            confirm_button = self.handler.element_finder.wait_for_element_clickable('confirm_invite')
            action = "Invited"
        else:
            confirm_button = self.handler.element_finder.wait_for_element_clickable('confirm_dismiss')
            action = "Dismissed"

        if not confirm_button:
            self.logger.error(f"Failed to find {action} confirmation button for {target_nickname}")
            await self._close_profile(open_result)
            return {'error': f'Failed to find {action} confirmation button', 'user': target_nickname}

        confirm_button.click()
        self.logger.info(f"Clicked {action} confirmation button")

        if enable:
            self.add_room_admin(target_nickname)
        else:
            self.remove_room_admin(target_nickname)

        await self._close_profile(open_result)

        return {'user': target_nickname, 'action': action}

    async def _close_profile(self, open_result: Optional[dict] = None) -> None:
        """关闭用户资料卡并在必要时恢复面板/抽屉状态。"""
        if hasattr(self.handler, "key_actions"):
            try:
                self.handler.key_actions.press_back()
            except Exception:
                pass
        recovery_manager = RecoveryManager.instance()
        recovery_manager.close_drawer('online_drawer')
        if open_result and open_result.get('source') == 'seat':
            try:
                from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver
                driver = SeatPanelDriver(self.handler)
                await driver.collapse()
            except Exception as e:
                self.logger.warning(f"Failed to collapse seat panel after profile action: {e}")
