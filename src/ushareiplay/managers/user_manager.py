import logging

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.online_drawer import Handover, OnlineDrawerManager
from ushareiplay.managers.online_drawer.driver import GIFT_ACTION_USE

YELLOW_DUCK_NAME = "小黄鸭"  # 礼物列表兜底礼物，固定为列表首位，点击即送无需点赠送

#: 打不开在线用户抽屉时的报错。沿用旧 `UserManager` 的原话，以免统一入口改掉聊天气泡
#: 里的文案。
OPEN_DRAWER_ERROR = 'Failed to open online users list'

#: 抽屉开了却没落定时的报错。刻意与上一句分开：旧实现里这就是两条不同的路径。
FIND_DRAWER_ERROR = 'Failed to find online users container'


class UserManager(Singleton):
    """在在线用户列表中查找指定用户并打开其资料页

    #435 起全部经由 `OnlineDrawerManager` 的抽屉会话进出抽屉：抽屉的开关、落定、翻页
    与关闭手势都在端口后面的适配器里，这里只剩「找谁」「找到之后做什么」这些判断。
    """

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("UserManager")
        return self._logger

    @property
    def drawer(self):
        """在线用户抽屉会话的唯一所有者。

        单例只查不建（ADR-0009，组合根装配）：拿不到就让整条定位链路显式失败，
        而不是悄悄退回裸 Appium 操作 —— 那正是 #428 之前的状态。
        """
        return OnlineDrawerManager.instance()

    async def open_user_profile(self, nickname: str):
        """打开目标用户的资料页（统一从在线用户列表查找）。

        Args:
            nickname: 目标用户。DB 的 canonical 名（主账号）或 Soul UI 可见昵称
                （分身名）都可以：两个命名域的解析在内部完成，调用方不必知道自己
                手里的是哪一个。
        """
        return await self.open_user_profile_from_online_list(nickname)

    async def open_user_profile_from_online_list(self, nickname: str):
        """
        在在线用户列表中查找指定用户并打开其资料页。

        全程在一个抽屉会话里：会话负责打开并等列表落定；这里负责翻页找人、点开资料卡。
        找不到人、卡片弹不出来、或会话自己打不开抽屉时，会话都会把抽屉收干净。

        成功时**不**收尾：抽屉连同资料卡一起交给调用方（送礼 / 房管要在卡片上继续
        操作），调用方用 `close_user_profile()` 收。这条交接由 `Handover` 显式声明，
        而不是给会话一个布尔开关 —— 开关只能整段会话生效，于是「没找到人就中途
        return」的失败路径也会被一起跳过收尾，抽屉就悬在屏幕上了。

        Args:
            nickname: 要查找的用户，canonical 名或分身名都可以。

        Returns:
            dict: 成功时返回 {'user': nickname}；失败时返回 {'error': str, 'user': nickname}。
        """
        drawer = self.drawer
        driver = drawer.driver
        handover = Handover()

        async with drawer.drawer_session(
            reason=f"user:open_profile:{nickname}",
            error_message=OPEN_DRAWER_ERROR,
            settle_error_message=FIND_DRAWER_ERROR,
            handover=handover,
        ) as open_error:
            if open_error:
                return {'error': open_error['error'], 'user': nickname}

            # 先解析命名域再进 UI 搜索：抽屉里只有可见昵称能定位到人，canonical 名直接
            # 拿去比 UI 文本永远不相等。
            visible_name = await drawer.resolve_visible_username(nickname)

            if not await drawer.find_member_in_drawer(visible_name):
                self.logger.warning(f"未找到用户 {visible_name}")
                return {
                    'error': 'User not found in online users list',
                    'user': nickname,
                }

            if not await driver.open_member_profile(visible_name):
                self.logger.error(f"Failed to click user element: {visible_name}")
                return {'error': 'Failed to click user element', 'user': nickname}

            self.logger.info(f"Clicked user element for {visible_name}")
            handover.release()
            return {'user': nickname}

    async def close_user_profile(self) -> None:
        """把交接出去的资料卡收回房间。

        资料卡与抽屉共用同一个 `ivClose`，所以这一步同时也是「回到房间」；收不掉就
        保持原状并记一条警告，绝不盲按返回 —— 那会连派对房间一起退掉。
        """
        await self.drawer.close_profile_card()

    async def send_gift(self, nickname: str):
        """
        执行送礼流程：先在在线用户列表中打开目标用户资料页，再点击送礼物并执行赠送/使用/背包逻辑。

        #438 起弹窗那几步全部经由抽屉端口：什么时候点、点哪一个、要不要收弹窗都是这里
        的判断，Appium 的键与坐标全在适配器里。资料页由 `open_user_profile` 通过
        `Handover` 交过来，本方法负责把交接到的两层弹窗都收干净。

        Args:
            nickname: 要送礼的目标用户。canonical 名（主账号）或分身名都可以，两个命名
                域的解析在 `open_user_profile` 内部完成。

        Returns:
            dict: 成功返回 {'success': str}；失败返回 {'error': str} 或 {'error': str, 'user': nickname}。
        """
        open_result = await self.open_user_profile(nickname)
        if 'error' in open_result:
            return open_result

        try:
            return await self._gift_on_card(self.drawer.driver)
        finally:
            # 收尾放在 finally：送成了、送挂了、还是中途抛了异常，弹窗与资料卡都不能留在
            # 屏幕上 —— 悬着的抽屉下一次盲按返回就会把派对房间一起带走。
            await self._close_gift_overlays()

    async def _gift_on_card(self, driver):
        """已经在资料卡上：点送礼物 -> 读弹窗 -> 送出。

        报错文案逐字沿用旧实现：这些字符串会原样进聊天气泡，迁移不是重写。
        """
        if not await driver.open_gift_entry():
            self.logger.info("未找到送礼物按钮")
            return {'error': '未找到送礼物入口'}

        self.logger.info("已点击送礼物")

        action = await driver.gift_popup_action()
        if action is None:
            self.logger.info("送礼界面未出现或超时")
            return {'error': '送礼界面未出现'}

        gift_name = await driver.read_gift_item_name()
        if gift_name is None:
            self.logger.warning('Failed to find gift')
            return {'error': 'Failed to find gift'}

        # 礼物列表兜底：背包为空时展示礼物列表，小黄鸭不会默认选中，直接点击即送出，无需点"赠送"
        if gift_name.strip() == YELLOW_DUCK_NAME:
            await driver.click_gift_item()
            self.logger.info(f"已点击{YELLOW_DUCK_NAME}，送出后关闭在线列表")
            return {'success': f'{gift_name} 送你啦'}

        # 灵魂力读数挪到小黄鸭那一条之后：它只出现在下面那行日志里，而小黄鸭那条日志
        # 根本不用它 —— 在真机上那是一次白等的 dump。
        soul_power = await driver.read_gift_soul_power()
        soul_points = soul_power if soul_power is not None else '0'

        # 点击失败只记警告不改道：旧实现在这里本来就不看点击结果，引入新的错误分支会
        # 改掉聊天气泡里的文案，而收尾已经由 `_close_gift_overlays` 兜住了。
        if not await driver.click_gift_action():
            self.logger.warning("点击赠送/使用按钮失败")

        self.logger.info(f"已点击赠送, gift_name: {gift_name} soul_points: {soul_points}")

        if action == GIFT_ACTION_USE:
            if not await driver.confirm_gift_use():
                self.logger.warning("未找到确认使用按钮")
                return {'error': '未找到确认使用按钮'}

            self.logger.info("已点击确认使用")

        return {'success': f'{gift_name} 送你啦'}

    async def _close_gift_overlays(self) -> None:
        """送完（或送挂）都按**相反顺序**分层收：先收送礼弹窗，再收资料卡连同抽屉。

        旧实现在两条失败路径上用 `key_actions.press_back()` 收弹窗，收掉的那层之下还
        悬着资料卡与抽屉 —— 而悬着的抽屉下一次盲按返回就会连派对房间一起带走
        （spec #426 问题陈述 #1）。这里两层都走页内手势，弹窗收不掉就只记警告，保持
        原状交给下一轮恢复流程。
        """
        await self.drawer.dismiss_gift_popup()
        await self.close_user_profile()

    async def send_private_message_to_user(self, nickname: str, message: str) -> bool:
        """
        向指定用户发送私聊消息。

        流程：
        1. 在线列表打开用户信息页
        2. 点击头像进入主页
        3. 点击私聊按钮进入私聊页
        4. 输入并发送消息
        5. 返回聊天室（私聊页的返回入口优先，兜底房间悬浮入口与主页返回）

        全程在一个抽屉会话里，且**保证**回到房间：资料卡与私聊页面上的任何一步失败，
        收尾都会走页面自己的返回入口，不盲按返回（盲按返回会连派对房间一起退掉）。

        任意一步失败返回 False，不抛异常。
        """
        try:
            self.handler.key_actions.switch_to_app()
            drawer = self.drawer
            driver = drawer.driver
            handover = Handover()

            async with drawer.drawer_session(
                reason=f"user:private_message:{nickname}",
                error_message=OPEN_DRAWER_ERROR,
                settle_error_message=FIND_DRAWER_ERROR,
                handover=handover,
            ) as open_error:
                if open_error:
                    self.logger.warning(
                        f"打开用户资料页失败: {nickname}, error={open_error['error']}"
                    )
                    return False

                visible_name = await drawer.resolve_visible_username(nickname)
                if not await drawer.find_member_in_drawer(visible_name):
                    self.logger.warning(f"未找到用户 {visible_name}")
                    return False
                if not await driver.open_member_profile(visible_name):
                    self.logger.warning(f"打开用户资料页失败: {nickname}")
                    return False

                # 卡片已经交到自己手里：接下来每一条失败路径都要自己回房间。
                handover.release()
                return await self._private_message_on_card(driver, nickname, message)
        except Exception as e:
            self.logger.error(f"私聊发送失败: {nickname}, error={e}")
            return False

    async def _private_message_on_card(self, driver, nickname: str, message: str) -> bool:
        """已经在资料卡上：点头像进主页 -> 私聊 -> 输入 -> 发送 -> 回房间。

        回房间放在 `finally` 里：消息发没发出去都要回，否则屏幕上会留下一张资料卡或一个
        私聊页，下一次盲按返回就会把它们连同房间一起带走。返回值同时要求「发出去了」与
        「回到房间了」—— 与旧实现一致，回不去就算这次私聊没成。
        """
        sent = False
        try:
            if not await driver.open_member_home():
                self.logger.warning(f"未找到头像入口: {nickname}")
                return False
            if not await driver.open_private_chat_page():
                self.logger.warning(f"未找到私聊按钮: {nickname}")
                return False
            if not await driver.type_private_message(message):
                self.logger.warning(f"未找到私聊输入框: {nickname}")
                return False
            if not await driver.submit_private_message():
                self.logger.warning(f"未找到私聊发送按钮: {nickname}")
                return False
            sent = True
        except Exception as e:
            self.logger.error(f"私聊发送失败: {nickname}, error={e}")
        finally:
            if not await driver.return_to_room():
                self.logger.warning(f"未找到返回聊天室入口: {nickname}")
                sent = False
        return sent
