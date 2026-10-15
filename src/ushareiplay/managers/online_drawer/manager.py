"""`OnlineDrawerManager` —— 在线用户抽屉**物理会话生命周期**的唯一所有者。

spec #426 记的问题是这份抽屉「无人认领」：`OnlineListScraper`、`UserManager`、
`AdminManager` 各自打开、各自关闭，关闭手势还互相冲突（`ivClose` / 遮罩点击 /
裸 `press_back`），任何一处漏收都会把抽屉悬在屏幕上，接着一次盲按返回就退房了。

本模块把「一次抽屉会话」收成一处：

    async with OnlineDrawerManager.instance().drawer_session("cmd:gift") as open_error:
        if open_error:
            return open_error
        <只在会话里做要做的动作>

四条归属规则，全部由这里保证：

1. **只关自己打开的那一次。** 进场时抽屉已经开着（被外层流程打开），本会话不夺取
   归属，退出后保持原状，让外层决定何时关。
2. **一定会收尾。** 正文抛异常也照样关，然后让异常继续往外走。
3. **绝不盲按返回。** 收尾只用 `ivClose`；连它都点不到时记一条警告、保持原状，
   而不是拿派对房间去赌一次 `press_back`（端口里根本没有这个原语）。
4. **交接是显式的。** 资料页流程（#435）的成功产物是抽屉之上的资料卡，因此它用
   `Handover` 把抽屉交出去；没有 `release()` 的任何路径（含中途 return 与抛异常）
   一律照常收尾。

在线名单抓取（#432）、资料页与私信（#435）、送礼（#438）、房管（#439）都只经由
这个会话进出抽屉；Appium 细节、坐标与落定时间全在端口后面的适配器里。
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.online_drawer.driver import OnlineDrawerDriverPort
from ushareiplay.managers.online_drawer.soul_driver import SoulOnlineDrawerDriver

#: 打不开抽屉时的默认报错文案。调用方可以传 `error_message` 换成自己面向用户的
#: 文本，以免统一入口后改变聊天气泡里的报错。
DEFAULT_OPEN_ERROR = 'Failed to open online users drawer'

#: 抽屉开了但没落定时的默认报错文案。与「打不开」分开表述：前者抽屉多半还开着，
#: 调用方重试有意义；后者连容器都没出现，重试之前应该先确认自己还在房间里。
DEFAULT_SETTLE_ERROR = 'Online users drawer did not settle'


class Handover:
    """一次抽屉会话里的**交接**信号。

    会话打开的抽屉默认在退出时收掉。但资料页流程（#435）的成功产物恰恰是抽屉之上的
    那层资料卡 —— 卡片与抽屉共用同一个 `ivClose`，此时收尾等于把刚交出去的东西拆掉。
    正文调用 `release()` 把抽屉连同资料卡一起交给调用方，收尾责任随之转移，调用方
    用 `close_profile_card()` / `return_to_room()` 收。

    刻意做成一个显式对象，而不是一个布尔开关：开关只能整段会话生效，于是「没找到人
    就中途 return」这类**失败**路径也会被跳过收尾，把抽屉悬在屏幕上 —— 而悬着的抽屉
    下一次盲按返回就会把房间一起带走（spec #426 问题陈述 #1）。
    """

    def __init__(self):
        self._released = False

    def release(self) -> None:
        """声明「抽屉与资料卡归调用方了」，本会话不再收尾。"""
        self._released = True

    @property
    def released(self) -> bool:
        return self._released


class OnlineDrawerManager(Singleton):
    """在线用户抽屉会话的唯一所有者：需要时打开、保证收尾、只关自己开的那次。

    Args:
        handler: 注入的 `SoulHandler`。提供 `logger` 与 `controller`（后者是 UI 独占
            锁的持有者）。
        driver: 抽屉 UI 端口适配器。`None` 时装配生产适配器。
        name_resolver: 注入的 async 命名域解析器，签名 `(str) -> str`。ADR-0009
            要求依赖只在构造期进入，因此这里**不**在模块内 import `InfoManager`
            —— 组合根传 `InfoManager.instance().resolve_visible_username` 进来。
            `None` 表示尚未接线（离线装配），此时按恒等处理。
    """

    def __init__(self, handler=None, driver=None, name_resolver=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._driver = driver if driver is not None else SoulOnlineDrawerDriver(handler)
        self._name_resolver = name_resolver

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, 'logger', None) or logging.getLogger(
                "ushareiplay.managers.online_drawer.manager"
            )
        return self._logger

    @property
    def handler(self):
        return self._handler

    @property
    def driver(self) -> OnlineDrawerDriverPort:
        """抽屉 UI 端口。None 表示组合根漏了接线（离线装配或接线漏了）。"""
        return self._driver

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def drawer_session(
        self,
        reason: str = "",
        *,
        error_message: Optional[str] = None,
        settle_error_message: Optional[str] = None,
        handover: Optional[Handover] = None,
    ):
        """抽屉开着的异步上下文：需要时才打开，且只关掉自己打开的那一次。

        Args:
            reason: UI 独占锁的持有理由，写进锁的调试日志，便于排障时看清是谁在
                占着屏幕。
            error_message: 打不开时返回给调用方的文案。
            settle_error_message: 抽屉开了却没落定时的文案。与「打不开」分开传入，
                因为调用方面向用户的报错里这两句本来就不一样，合并会改掉聊天气泡里
                的话。
            handover: 可选的交接信号。正文调用 `handover.release()` 时，本会话不再
                收尾，把打开的抽屉交给调用方；没有 `release()`（含中途 return 与抛
                异常）时照常收尾。传 `None`（默认）就是本模块的原始行为。

        Yields:
            error dict（抽屉不可用）或 None（会话已就绪）。失败时**不会** yield 一个
            「假装开着」的抽屉，调用方据此提前返回，不必在会话里做无用功。

        Raises:
            with 正文抛出的异常原样继续往外走；关闭动作已经先做完了。
        """
        async with self._ui_session(reason):
            driver = self._require_driver()

            if await driver.is_open():
                # 抽屉不是本会话打开的：不夺取归属。外层（命令链上的持有者）决定
                # 何时关，这里退出后保持原状。
                yield None
                return

            open_error = error_message or DEFAULT_OPEN_ERROR
            result = await driver.open(error_message=open_error)
            if isinstance(result, dict) and 'error' in result:
                self.logger.warning(f"[online_drawer] {reason or 'session'} 打不开在线用户抽屉")
                yield {'error': open_error}
                return

            self.logger.info(f"[online_drawer] {reason or 'session'} 已打开在线用户抽屉")
            if not await driver.wait_for_settle():
                # 抽屉是本会话打开的，必须收尾 —— 否则它会悬在屏幕上等着被下一次
                # 盲按返回误退出房间。
                self.logger.warning(
                    f"[online_drawer] {reason or 'session'} 抽屉打开后未能落定，收尾关闭"
                )
                await self._ensure_closed()
                yield {'error': settle_error_message or error_message or DEFAULT_SETTLE_ERROR}
                return

            try:
                yield None
            except BaseException:
                # 抛异常一律收尾：交接只发生在正文的成功路径上，抛出来的一律不算。
                await self._ensure_closed()
                raise
            if handover is None or not handover.released:
                await self._ensure_closed()

    async def close_profile_card(self) -> None:
        """交接的另一半：把资料卡连同抽屉收回房间。

        不夺取归属 —— 只在卡片真的悬着时才动手，且用端口自己的手势收。收不掉就记一条
        警告并保持原状，交给下一轮恢复流程，绝不盲按返回。
        """
        try:
            async with self._ui_session("online_drawer:close_profile_card"):
                driver = self._require_driver()
                if not await driver.dismiss_profile_card():
                    self.logger.warning(
                        "[online_drawer] 未能通过 ivClose 收起资料卡，保持原状等待下一轮恢复"
                    )
                    return
                self.logger.info("[online_drawer] 资料卡已收起")
        except Exception as e:
            # 收尾失败不能让调用方的正常结果变成异常（同 `_ensure_closed` 的理由）。
            self.logger.warning(f"[online_drawer] 收起资料卡时出错: {e}")

    async def dismiss_gift_popup(self) -> None:
        """交接的另一半之一：把还盖在资料卡上的送礼弹窗收掉。

        与 `close_profile_card` 同一套规矩 —— 持 UI 独占锁、只在弹窗真的悬着时才动手、
        收不掉就记一条警告并保持原状，绝不盲按返回。送礼流程（#438）用它替掉旧实现那两
        次 `press_back`：盲按返回会把弹窗收掉，顺手把资料卡与抽屉留在屏幕上。
        """
        try:
            async with self._ui_session("online_drawer:dismiss_gift_popup"):
                driver = self._require_driver()
                if not await driver.dismiss_gift_popup():
                    self.logger.warning(
                        "[online_drawer] 未能通过页内关闭键收起送礼弹窗，保持原状等待下一轮恢复"
                    )
                    return
                self.logger.info("[online_drawer] 送礼弹窗已收起")
        except Exception as e:
            # 收尾失败不能让调用方的正常结果变成异常（同 `close_profile_card` 的理由）。
            self.logger.warning(f"[online_drawer] 收送礼弹窗时出错: {e}")

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """持有 UI 独占锁。

        打开、落定、滚动、找人、关闭全程都在改页面结构；不持锁时 EventManager 的
        兜底 `press_back` 会在这些 await 点把抽屉当成未知页面关掉。

        controller 缺席（离线装配）时退化为不加锁；controller 在场但接口不符契约
        时直接抛错，而不是静默裸奔。
        """
        controller = getattr(self._handler, "controller", None) if self._handler else None
        if controller is None:
            yield
            return
        async with controller.ui_session(reason or "online_drawer"):
            yield

    async def _ensure_closed(self) -> None:
        """收尾：只走 `ivClose`，点不到就记警告并保持原状。

        刻意没有第二条路径。旧实现在这里会 `press_back` 再点遮罩，而盲按返回正是
        spec #426 问题陈述 #1 里退房的原因；留在屏幕上的抽屉只是难看一次，退出派对
        房间则是事故。
        """
        try:
            driver = self._require_driver()
            if not await driver.is_open():
                return
            if await driver.close():
                self.logger.info("[online_drawer] 在线用户抽屉已关闭")
                return
            self.logger.warning(
                "[online_drawer] 未能通过 ivClose 关闭在线用户抽屉，保持原状等待下一轮恢复"
            )
        except Exception as e:
            # 收尾失败不能让调用方的正常结果变成异常：抽屉还开着是「难看」，
            # 抛出去是「任务失败」，后者更糟。
            self.logger.warning(f"[online_drawer] 关闭在线用户抽屉时出错: {e}")

    # ------------------------------------------------------------------
    # 命名域
    # ------------------------------------------------------------------

    async def resolve_visible_username(self, username: str) -> str:
        """把任意命名域的名字解析成 Soul UI 上可见的昵称（分身名）。

        房间里只有 UI 名字是可用的坐标：在线列表、资料页、麦位弹窗都按屏幕上
        显示的文本找人。而调用方手里的名字经常是 DB 的 canonical 名（主账号），
        两个命名域的字符串**不同**，直接拿去和 UI 文本比对永远不相等。
        跨命名域判同一身份要用 `UserDAO.is_same_identity(...)`，不能 `==`。

        因此凡是拿名字去 UI 里找人的路径，都必须先过这里一次。

        Args:
            username: canonical 名或任一分身名。

        Returns:
            解析出的 UI 可见昵称。**没有配置解析器时（离线装配、单元测试）原样返回**
            —— 那时候调用方给的名字本来就是 UI 文本，恒等处理不会改变任何行为。
        """
        resolver = self._name_resolver
        if resolver is None:
            return username
        return await resolver(username)

    def _require_driver(self) -> OnlineDrawerDriverPort:
        driver = self._driver
        if driver is None:
            # 构造时显式传了 driver=None：这是接线漏了，不是业务失败。悄悄降级成
            # 「App 不可用」会让生产环境整条抽屉链路静默失效。
            raise RuntimeError(
                "OnlineDrawerManager drawer actions require an OnlineDrawerDriverPort adapter; "
                "construct OnlineDrawerManager with driver=... at the composition root."
            )
        return driver
