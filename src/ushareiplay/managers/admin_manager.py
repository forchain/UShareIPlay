"""房间管理员的授予与解除 —— #439 起全程走 `OnlineDrawerManager` 的抽屉会话。

整条流程收在一个会话里：开抽屉 -> 翻页找人 -> 点开资料卡 -> 在卡片上点房管开关 ->
点确认框 -> 记账。收尾按**相反的顺序**分层收：先收可能悬着的确认框，再收资料卡
（收卡片时抽屉一起收），两层都走页内手势。

旧实现在这条链上散落着三处 `RecoveryManager` 的关抽屉兜底，以及两条幂等分支（在
「已经是房管」「还不是房管」）上各一次盲按返回。那两处盲按返回正是 spec #426 问题
陈述 #1 点名的退房来源：它们只收掉最上面那层确认框，底下的资料卡与抽屉照样悬在屏幕
上等着被下一次盲按返回带走。现在两处都由 `_close_admin_overlays` 兜住，收不掉只记警告
并保持原状，交给下一轮恢复流程。
"""

import logging

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.online_drawer import Handover, OnlineDrawerManager
from ushareiplay.managers.online_drawer.driver import (
    ADMIN_ACTION_DISMISS,
    ADMIN_ACTION_INVITE,
    ADMIN_LABEL_DISMISS,
    ADMIN_LABEL_INVITE,
)

#: 打不开在线用户抽屉时的报错。刻意与 `UserManager` 那一份逐字相同：这些字符串会原样
#: 进聊天气泡，而 :admin 过去就是经由 `open_user_profile` 报出来的。
OPEN_DRAWER_ERROR = 'Failed to open online users list'

#: 抽屉开了却没落定时的报错。与上一句分开：旧实现里这就是两条不同的路径，合成一句会
#: 改掉聊天气泡里的措辞。
FIND_DRAWER_ERROR = 'Failed to find online users container'

#: 两条成功路径的 `action` 文案，会原样进聊天气泡，迁移不是重写。
ACTION_INVITE = 'Invited'
ACTION_DISMISS = 'Dismissed'


class AdminManager(Singleton):
    """房间管理员状态的唯一记账处，房管的授予与解除也在这里执行。

    房管开关是资料卡上的**一枚**控件，文案决定它是邀请还是解除；「现在是不是房管」
    因此是本类的判断，端口只负责读文案、点按钮。屏幕才是真相，本地 `_room_admins`
    只是它的抄写：幂等分支里也先按屏幕把抄写修正，再回报一句给聊天。
    """

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

    @property
    def drawer(self):
        """在线用户抽屉会话的唯一所有者。

        单例只查不建（ADR-0009，组合根装配）：拿不到就让整条链路显式失败，而不是悄悄
        退回裸 Appium 操作 —— 那正是 #428 之前的状态。
        """
        return OnlineDrawerManager.instance()

    async def manage_admin(self, enable: bool, target_nickname: str):
        """
        管理管理员状态：在在线列表中打开目标用户资料页，再执行邀请/解除管理。

        全程在一次抽屉会话里，且**保证**收拾干净：确认框、资料卡、抽屉三层在成功与
        失败两条路上都会被收一遍，收不掉只记警告，绝不盲按返回（盲按返回会连派对房间
        一起退掉）。

        Args:
            enable: True 邀请为管理员，False 解除管理员
            target_nickname: 被操作的用户昵称。canonical 名（主账号）或 Soul UI 可见昵称
                （分身名）都可以：两个命名域的解析在抽屉会话里完成。

        Returns:
            dict: 成功含 user/action，失败含 error/user
        """
        drawer = self.drawer
        driver = drawer.driver
        handover = Handover()

        async with drawer.drawer_session(
            reason=f"admin:{target_nickname}",
            error_message=OPEN_DRAWER_ERROR,
            settle_error_message=FIND_DRAWER_ERROR,
            handover=handover,
        ) as open_error:
            if open_error:
                return {'error': open_error['error'], 'user': target_nickname}

            # 先解析命名域再进 UI 搜索：抽屉里只有可见昵称能定位到人，canonical 名直接
            # 拿去比 UI 文本永远不相等。解析器抛错就按原名找，与旧实现在这里的兜底一致。
            visible_name = await self._resolve_visible_name(drawer, target_nickname)

            if not await drawer.find_member_in_drawer(visible_name):
                self.logger.warning(f"未找到用户 {visible_name}")
                return {
                    'error': 'User not found in online users list',
                    'user': visible_name,
                }

            if not await driver.open_member_profile(visible_name):
                self.logger.error(f"Failed to click user element: {visible_name}")
                return {'error': 'Failed to click user element', 'user': visible_name}

            self.logger.info(f"Clicked user element for {visible_name}")
            # 卡片已经交到自己手里：接下来每一条路径（含失败与中途 return）都要自己收。
            handover.release()
            try:
                # 房间管理员按 UI 名字记账：麦位观测与 :info 都用 slot.username（分身名）比对。
                return await self._toggle_on_card(driver, enable, visible_name)
            finally:
                await self._close_admin_overlays()

    async def _resolve_visible_name(self, drawer, nickname: str) -> str:
        """把 canonical 名解析成房间里可见的分身名；解析不了就按原名找。

        兜底刻意保留：旧实现在这里也是「解析抛异常就用原名继续」，而解析器是别处的
        单例，让它的一次抖动把整条房管流程变成硬失败并不划算。
        """
        try:
            return await drawer.resolve_visible_username(nickname)
        except Exception:
            return nickname

    async def _toggle_on_card(self, driver, enable: bool, target_nickname: str) -> dict:
        """已经在资料卡上：读开关文案 -> 判幂等 -> 点开关 -> 点确认。

        幂等判定逐字沿用旧实现：文案是「解除管理」说明**已经是**房管，此时再邀请就是
        多余动作；文案是「管理邀请」说明还不是，去解除同理。两条分支都先把本地
        `_room_admins` 抄成与屏幕一致的状态再返回 —— 聊天里那句「已经 / 还不是管理员」
        由屏幕决定，不由本地名单决定。
        """
        label = await driver.read_admin_invite_label()
        if label is None:
            return {'error': 'Failed to find manager invite button', 'user': target_nickname}

        if enable:
            if label == ADMIN_LABEL_DISMISS:
                self.add_room_admin(target_nickname)
                return {'error': '你已经是管理员了', 'user': target_nickname}
            action = ACTION_INVITE
        else:
            if label == ADMIN_LABEL_INVITE:
                self.remove_room_admin(target_nickname)
                return {'error': '你还不是管理员', 'user': target_nickname}
            action = ACTION_DISMISS

        # 点开关失败只记警告不改道：旧实现在这里本来就不看点击结果，真正的判据是下一步
        # 「确认框有没有出来」，它有自己的一句报错（见下）。引入新分支会凭空多出一句
        # 聊天气泡里从来没有过的话。
        if not await driver.click_admin_invite():
            self.logger.warning("点击管理邀请按钮失败")
        self.logger.info("Clicked manager invite button")

        if not await driver.confirm_admin_action(
            ADMIN_ACTION_INVITE if enable else ADMIN_ACTION_DISMISS
        ):
            self.logger.error(
                f"Failed to find {action} confirmation button for {target_nickname}"
            )
            return {'error': f'Failed to find {action} confirmation button', 'user': target_nickname}

        self.logger.info(f"Clicked {action} confirmation button")

        if enable:
            self.add_room_admin(target_nickname)
        else:
            self.remove_room_admin(target_nickname)

        return {'user': target_nickname, 'action': action}

    async def _close_admin_overlays(self) -> None:
        """按**相反顺序**分层收：先收确认框，再收资料卡连同抽屉。

        收尾放在 `finally` 里：邀请成了、邀请挂了、还是幂等分支提前返回，三层都不能留在
        屏幕上 —— 悬着的抽屉下一次盲按返回就会把派对房间一起带走（问题陈述 #1）。两层都
        走页内手势，收不掉只记警告并保持原状。
        """
        drawer = self.drawer
        await drawer.dismiss_admin_confirm()
        await drawer.close_profile_card()
