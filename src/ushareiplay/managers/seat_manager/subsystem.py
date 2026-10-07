"""座位子系统的唯一实现：占座、下麦、占座人清退、预约数据流。

合并前这些能力散在四个互相独立的单例里（`SeatUIManager` 管面板、`SeatingManager` 管
占座、`SeatCheckManager` 管进房检查与清人、`ReservationManager` 管预约数据），外加
一个逐方法转发的 `SeatManager` 门面。同一个面板甚至有两份展开/收起/滚动实现。
本模块把它们收成一处：`SeatSubsystem` 持有全部真实逻辑与面板驱动，四个旧单例退化成
转发件（#400），接线层由 #401 收口，旧单例由 #402 删除。

## 依赖方向

`SeatSubsystem` 不依赖任何一个旧单例。旧单例持有（并可被绑定到）一个子系统，实现
一律从子系统拿。接线层把四个旧单例都绑到同一个子系统上之后，它们就不再是四份实现，
而是同一份实现的四个入口。

## 面板协作者的接缝

`panel` 属性是本模块内部的面板入口。三个来源按优先级：

1. 外部注入的 `seat_ui` 对象（既有测试用这种方式钉住面板动作的调用时序）；
2. 绑定的旧 `SeatUIManager` **句柄**只作为对外暴露的 `seat_ui` 属性，面板动作一律
   走 3 —— 否则子系统调句柄、句柄又回调子系统，就是无限递归；
3. 内置的 `_DriverSeatPanel`，把 `SeatPanelDriver` 适配成旧 `seat_ui` 的契约。

`SeatPanelDriver`（#395）是面板展开/收起/滚动的唯一实现；`SeatUIManager` 里那份
近重复副本在本票退役。
"""

import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from ushareiplay.dal import SeatReservationDAO, UserDAO
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver

# 旧单例打上这个标记，子系统据此识别「这是自己实现的一个转发件」，
# 从而不会把它当成外部注入的协作者再回调自己。
SUBSYSTEM_ADAPTER_ATTR = "_seat_subsystem_adapter"


def _is_adapter(obj) -> bool:
    """这个对象是不是本子系统自己的转发件（是的话不能当外部协作者回指）。"""
    return bool(getattr(obj, SUBSYSTEM_ADAPTER_ATTR, False))


def _foreign(obj):
    """取出真正由外部提供的协作者；转发件（自带实现的一端）不算。"""
    return obj if obj is not None and not _is_adapter(obj) else None


class SubsystemHandle:
    """旧单例共用的转发基类（#400 临时保留，#402 连同四个旧单例一起删）。

    每个旧单例仍然是单例、仍然是接线层初始化出来的那一个，但它不再持有实现：
    方法一律回到 `SeatSubsystem`。没被 `SeatManager` 绑定的旧单例（比如单元测试
    单独 `SeatingManager.initialize(...)`）会按自己的构造参数自建一个子系统 ——
    于是「单独用」和「接线用」走的是同一份实现。
    """

    # 供 SeatSubsystem 识别（见 _is_adapter）：这是自己实现的一个端点，不能回指。
    _seat_subsystem_adapter = True

    def __init__(self, handler=None):
        self._handler = handler
        self._bound_subsystem = None
        self._own_subsystem = None

    # -- handler：旧单例对外暴露的属性，写入要一路传到子系统与面板驱动 --

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        self._handler = value
        for subsystem in (self._bound_subsystem, self._own_subsystem):
            if subsystem is not None:
                subsystem.handler = value

    def subsystem_kwargs(self) -> dict:
        """自建子系统时用的构造参数，由子类按各自的注入点覆盖。"""
        return {}

    def bind_subsystem(self, subsystem):
        """接到共享子系统上（由 `SeatManager` 在接线时调用）。"""
        self._bound_subsystem = subsystem
        return self

    @property
    def subsystem(self) -> "SeatSubsystem":
        if self._bound_subsystem is not None:
            return self._bound_subsystem
        if self._own_subsystem is None:
            self._own_subsystem = SeatSubsystem(self._handler, **self.subsystem_kwargs())
        return self._own_subsystem


class _DriverSeatPanel:
    """`SeatPanelDriver` 的旧 `seat_ui` 契约适配层（子系统内部面板入口）。

    方法名与 `SeatUIManager` 的旧契约一一对应，面板行为本身完全由驱动决定 ——
    这里不再有第二份展开/收起/滚动的判断逻辑。
    """

    def __init__(self, driver: SeatPanelDriver):
        self.driver = driver

    # 旧 seat_ui 契约里 handler 是可写的，`SeatObservationManager.bind_handler`
    # 换手时会写 `seat_ui.handler`（ADR-0009 第 5 条：同步观测器及其 UI 委派）。
    # 驱动上的 logger 是构造期快照，委派不把换手透传下去就等于让它一直往旧
    # handler 的 logger 上写。
    @property
    def handler(self):
        return self.driver.handler

    @handler.setter
    def handler(self, value):
        self.driver.handler = value

    def check_seats_state(self) -> bool:
        return self.driver.is_expanded()

    async def expand_seats(self) -> bool:
        return await self.driver.expand()

    async def collapse_seats(self) -> bool:
        return await self.driver.collapse()

    async def expand_and_find_desks(self) -> Optional[list]:
        return await self.driver.expand_and_find_desks()

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100) -> bool:
        return self.driver.scroll_to_row(desk_index, seat_desks, duration=duration)

    @property
    def is_expanded(self) -> bool:
        return self.driver.expanded


class SeatSubsystem:
    """座位子系统的唯一实现。

    刻意不是单例：handler 与协作者都由构造注入（与 `SeatPanelDriver` 同一原则），
    由 `SeatManager` 门面持有并绑定四个旧单例句柄。
    """

    # 供四个旧单例识别自己用的标记（见 _is_adapter）。
    _seat_subsystem_adapter = True

    def __init__(
        self,
        handler=None,
        panel_driver=None,
        observation=None,
        seat_ui=None,
        seat_check=None,
        reservation=None,
        seating=None,
    ):
        self._handler = handler
        self._panel_driver = panel_driver
        self._observation = observation
        self._message_dispatch = None
        # 占座游标：SeatingManager 原本持有的两个状态，合并后归子系统所有。
        self.current_desk_index = 0
        self.current_side = None

        # 对外暴露的协作者句柄，由 SeatManager 接线时用 attach_handles 回填（#401 收口）。
        self.seat_ui = None
        self.seat_check = None
        self._driver_panel = None

        # 后向兼容接缝（#400 临时保留，#402 连同旧单例一起删）：
        # 既有测试/扩展注入的**外部**协作者优先于子系统自带的实现。
        # 旧单例句柄不算外部协作者 —— 交给它实现就等于让子系统回调自己的转发件。
        self._foreign_seat_ui = _foreign(seat_ui)
        self._foreign_seat_check = _foreign(seat_check)
        self._foreign_reservation = _foreign(reservation)
        self._foreign_seating = _foreign(seating)

        # 非转发件的 seat_ui 同时是对外可见的协作者；转发件要等 attach_handles。
        if self._foreign_seat_ui is not None:
            self.seat_ui = seat_ui
        if self._foreign_seat_check is not None:
            self.seat_check = seat_check

    def attach_handles(self, seat_ui=None, seat_check=None) -> None:
        """回填接线层给的旧单例句柄，让它们成为本子系统的对外入口。

        句柄本身只是转发件：它们的方法会回到这里来，所以面板动作一律走 `panel`
        而不是走 `seat_ui`，否则就是子系统调句柄、句柄又回调子系统。
        """
        if seat_ui is not None:
            self.seat_ui = seat_ui
        if seat_check is not None:
            self.seat_check = seat_check

    # ------------------------------------------------------------------
    # 协作者
    # ------------------------------------------------------------------
    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        self._handler = value
        if self._panel_driver is not None:
            self._panel_driver.handler = value

    @property
    def panel_driver(self) -> SeatPanelDriver:
        """座位面板的 UI 驱动：点名片、读占座人昵称、按证据关弹窗。

        构造注入优先，缺省时按需自建并缓存。驱动刻意不是单例（它没有全局状态）。
        """
        if self._panel_driver is None:
            self._panel_driver = SeatPanelDriver(self.handler)
        return self._panel_driver

    @property
    def panel(self):
        """本子系统内部的面板入口（所有面板动作都从这里走）。"""
        if self._foreign_seat_ui is not None:
            return self._foreign_seat_ui
        if self._driver_panel is None or self._driver_panel.driver is not self.panel_driver:
            self._driver_panel = _DriverSeatPanel(self.panel_driver)
        return self._driver_panel

    @property
    def observation(self):
        """观测管理器的只读查找入口；刻意不在构造期急初始化那个单例。"""
        if self._observation is not None:
            return self._observation
        from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager

        if SeatObservationManager.is_initialized():
            return SeatObservationManager.instance()
        return None

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.handler)
        return self._message_dispatch

        # ------------------------------------------------------------------
    # UI 独占
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """独占 UI 执行权，契约与 SeatPanelDriver.ui_session 一致。

        展开座位面板、滚动、点头像弹窗、点「请下麦」全程会改页面结构。若不持锁，
        EventManager 的兜底 press_back 会在这些 await 点把弹窗当成未知页面关掉，
        手里那个 seat_off 句柄随之失效（StaleElementReferenceException）。

        controller 缺席（单元测试）时退化为不加锁；controller 在场但接口不符
        契约时直接抛错，而不是静默裸奔。
        """
        ctrl = getattr(self.handler, "controller", None) if self.handler else None
        if ctrl is None:
            yield
            return
        async with ctrl.ui_session(reason):
            yield

    # ------------------------------------------------------------------
    # 面板
    # ------------------------------------------------------------------
    def check_seats_state(self) -> bool:
        return self.panel.check_seats_state()

    async def expand_seats(self) -> bool:
        return await self.panel.expand_seats()

    async def collapse_seats(self) -> bool:
        return await self.panel.collapse_seats()

    async def expand_and_find_desks(self) -> Optional[list]:
        return await self.panel.expand_and_find_desks()

    def scroll_to_row(self, desk_index, seat_desks=None, duration=100) -> bool:
        return self.panel.scroll_to_row(desk_index, seat_desks, duration=duration)

    async def prepare_for_chat_scan(self) -> bool:
        """聊天历史扫描前把座位面板收回原状。"""
        is_expanded = self.check_seats_state()
        if is_expanded:
            return await self.collapse_seats()
        return True

    # ------------------------------------------------------------------
    # 预约数据（ReservationManager 合并进来）
    # ------------------------------------------------------------------
    async def reserve_seat(self, username: str, seat_number: int) -> dict:
        """给用户预留一个麦位。"""
        if self._foreign_reservation is not None:
            return await self._foreign_reservation.reserve_seat(username, seat_number)
        return await self._reserve_seat(username, seat_number)

    async def _reserve_seat(self, username: str, seat_number: int) -> dict:
        try:
            self.handler.logger.info(f"Starting seat reservation process for user {username} on seat {seat_number}")

            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                self.handler.logger.error(f"Failed to get or create user {username}")
                return {'error': f'Failed to get or create user {username}'}
            self.handler.logger.info(f"User {username} (level {user.level}) retrieved/created successfully")

            # Remove any existing reservation for the user
            existing_reservation = await SeatReservationDAO.get_reservation_by_user_id(user.id)
            if existing_reservation:
                self.handler.logger.info(
                    f"Found existing reservation for user {username} on seat {existing_reservation.seat_number}, removing it")
                await SeatReservationDAO.remove_reservation(existing_reservation)
                self.handler.logger.info("Existing reservation removed successfully")

            # Check if seat is already reserved
            existing_reservation = await SeatReservationDAO.get_seat_reservation(seat_number)
            if existing_reservation:
                self.handler.logger.info(
                    f"Seat {seat_number} is already reserved by {existing_reservation.user.username} (level {existing_reservation.user.level})")
                # If the seat is reserved, check if current user has higher level
                if user.level <= existing_reservation.user.level:
                    self.handler.logger.warning(
                        f"User {username} (level {user.level}) cannot override reservation of {existing_reservation.user.username} (level {existing_reservation.user.level})")
                    return {
                        'error': f'Seat {seat_number} is already reserved by {existing_reservation.user.username} with level {existing_reservation.user.level}'}
                # If current user has higher level, remove the existing reservation
                self.handler.logger.info(
                    f"User {username} has higher level ({user.level} > {existing_reservation.user.level}), removing existing reservation")
                await SeatReservationDAO.remove_reservation(existing_reservation)
                self.handler.logger.info("Existing reservation removed successfully")

            # Create reservation in database
            duration_hours = min(max(user.level, 1), 24)  # Duration is user's level, between 1 and 24 hours
            self.handler.logger.info(f"Creating new reservation: seat {seat_number} for {duration_hours} hours")
            reservation = await SeatReservationDAO.create(user, seat_number, duration_hours)
            self.handler.logger.info(
                f"Reservation created successfully: no. {reservation.id} seat {seat_number} for {duration_hours} hours")

            # 落库后直接清位，不再经由 SeatCheckManager 绕一圈（#400 合并）。
            await self.check_user_specific_seat(username, seat_number)

            return {'success': f'Successfully reserved seat {seat_number} for {duration_hours} hours'}

        except Exception as e:
            self.handler.log_error(f"Error reserving seat: {traceback.format_exc()}")
            return {'error': f'Failed to reserve seat: {str(e)}'}

    async def remove_user_reservation(self, username: str) -> dict:
        """删除某个用户的麦位预留（纯数据操作）。"""
        if self._foreign_reservation is not None:
            return await self._foreign_reservation.remove_user_reservation(username)
        return await self._remove_user_reservation(username)

    async def _remove_user_reservation(self, username: str) -> dict:
        try:
            # Get or create user first
            user = await UserDAO.get_or_create(username)
            if not user:
                return {'error': f'Failed to get or create user {username}'}

            # Get user's reservation
            reservation = await SeatReservationDAO.get_reservation_by_user_id(user.id)
            if not reservation:
                return {'error': f'No reservation found for user {username}'}

            # Remove from database
            await SeatReservationDAO.remove_reservation(reservation)

            return {'success': f'Successfully removed reservation for seat {reservation.seat_number}'}

        except Exception as e:
            self.handler.log_error(f"Error removing reservation: {traceback.format_exc()}")
            return {'error': f'Failed to remove reservation: {str(e)}'}

    # ------------------------------------------------------------------
    # 进房检查与占座人清退（SeatCheckManager 合并进来）
    # ------------------------------------------------------------------
    async def check_seats_on_entry(self, username: str = None):
        """用户进房/回房时检查其预留麦位。"""
        if self._foreign_seat_check is not None:
            return await self._foreign_seat_check.check_seats_on_entry(username)
        return await self._check_seats_on_entry(username)

    async def _check_seats_on_entry(self, username: str = None):
        if self.handler is None or not username:
            self.handler.logger.warning("check_seats_on_entry called with invalid parameters")
            return

        try:
            self.handler.logger.info(f"Starting seat check for user {username}")

            # Get user's reservation
            user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
            if not user_reservation:
                self.handler.logger.info(f"No reservation found for user {username}")
                return

            self.handler.logger.info(f"Found reservation for user {username} on seat {user_reservation.seat_number}")

            # Check if reservation is still valid
            now = datetime.now()
            self.handler.logger.info(f"Current time: {now}")

            # Ensure both datetimes are timezone-naive
            start_time = user_reservation.start_time
            if start_time.tzinfo is not None:
                # Convert to timezone-naive if needed
                from datetime import timezone
                start_time = start_time.replace(tzinfo=None)
                self.handler.logger.info(f"Converted start_time to timezone-naive: {start_time}")

            end_time = start_time + timedelta(hours=user_reservation.duration_hours)
            self.handler.logger.info(f"Reservation period: {start_time} to {end_time}")

            if now > end_time:
                # Reservation expired, remove it
                self.handler.logger.info(f"Reservation for user {username} has expired, removing it")
                await SeatReservationDAO.remove_reservation(user_reservation)
                self.handler.logger.info(f"Successfully removed expired reservation for user {username}")
                return

            # Reservation is valid, auto-renew it
            duration_hours = min(max(user_reservation.user.level, 1),
                                 24)  # Duration is user's level, between 1 and 24 hours
            self.handler.logger.info(
                f"Auto-renewing reservation for user {username} (level {user_reservation.user.level}) with duration {duration_hours} hours")

            await SeatReservationDAO.update_reservation_start_time(user_reservation.id, now)
            self.handler.logger.info(f"Successfully auto-renewed reservation for user {username}")

            user_reservation = await SeatReservationDAO.get_reservation_by_user_name(username)
            if not user_reservation:
                return

            await self.check_user_specific_seat(username, user_reservation.seat_number)

        except Exception as e:
            self.handler.log_error(f"Error checking seats: {traceback.format_exc()}")

    async def check_user_specific_seat(self, username: str, seat_number: int):
        """展开面板、滚到目标排，把占座人清掉换成目标用户。"""
        async with self._ui_session(f"seat_check:{seat_number}"):
            self.handler.logger.info("expanding seats for check")
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return
            self.handler.logger.info(f"found {len(seat_desks)} seat desks")

            # check and handle the user's specific seat
            self.handler.logger.info(f"checking specific seat {seat_number} for user {username}")

            desk_index = (seat_number - 1) // 2
            self.scroll_to_row(desk_index, seat_desks, duration=1000)
            if desk_index // 2 in (0, 2):
                await asyncio.sleep(0.5)

            await self._handle_occupied_seat(username, seat_desks, seat_number)

    async def _handle_occupied_seat(self, username: str, seat_desks, seat_number: int):
        """Handle an occupied seat by removing the occupant"""
        if self.handler is None:
            return

        # Determine if this is a left or right seat in the row
        is_left_seat = bool(seat_number % 2)
        side = 'left' if is_left_seat else 'right'
        desk_index = (seat_number - 1) // 2
        desk = seat_desks[desk_index]

        # 麦位 DOM 上的占用判据（label 节点）仍由本模块自己读：它决定「要不要点开
        # 名片」，与名片本身无关。
        seat_element = self.handler.element_finder.find_child_element(desk, f'{side}_seat')
        seat_label = self.handler.element_finder.find_child_element(seat_element, f'{side}_label')

        if not seat_element:
            self.handler.logger.error(f"Cannot find seat element for seat {seat_number}")
            self.message_dispatch.send_screen_message(f"Failed to locate seat {seat_number} for {username}")
            return

        if not seat_label:
            self.handler.logger.warning(f"No occupant for seat {seat_number}")
            return
        self.handler.logger.info(f"Found seat {seat_number} with label {seat_label.text if seat_label else 'None'}")

        # Send welcome message only when seat is occupied to reduce message frequency
        self.message_dispatch.send_screen_message(f"Welcome {username}!")

        # wait for input dialog disappear
        await asyncio.sleep(1)

        # 点开占座人的名片、读昵称、最后按证据关掉它，整段交给 SeatPanelDriver：
        # 房间里一次盲按 back 就是退出派对房间，本模块不再持有任何一次 back。
        # 顺序也随之调整：名片必须先点开，「请下麦」按钮才可能读到。
        # prefer_state=False：这条链路要读 seat_off（「请下麦」），必须点 UserView
        # 而不是默认的 ClState。迁移前点的一直是 seat 节点，重构不该顺手改掉一个
        # 没有证据支持的点击目标 —— 点 ClState 弹出的名片是否带 seat_off 全仓无
        # 从验证（真机 dump 里没有 tvSeatDownUp），点错的症状是静默的：
        # 「Unable to manage seat N」，占位不再清人。
        async with self.panel_driver.avatar_card(
            desk, side, seat_number, prefer_state=False
        ) as card:
            if card.opened:
                self.handler.logger.info(f"Opened seat {seat_number} card to check the occupant")
            souler_name_text = card.name if card.opened else None
            if not souler_name_text:
                self.handler.logger.error(f"No souler name found for seat {seat_number}")
                self.message_dispatch.send_screen_message(f"Failed to verify occupant on seat {seat_number}")
                return

            if souler_name_text == username:
                self.handler.logger.error(f"Souler {username} is already in seat {seat_number}")
                # No message needed - user is already seated successfully
                return

            user = await UserDAO.get_by_username(username)
            souler = await UserDAO.get_by_username(souler_name_text)
            if user and souler and user.level <= souler.level:
                self.handler.logger.info(
                    f"Souler {souler_name_text} has higher or equal level ({souler.level}) than {username} ({user.level}), skipping")
                self.message_dispatch.send_screen_message(f"Cannot seat {username}: Seat {seat_number} occupied by higher level user")
                return

            # Wait for seat off button
            seat_off = self.handler.element_finder.wait_for_element_clickable('seat_off')
            if not seat_off:
                self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
                self.message_dispatch.send_screen_message(f"Unable to manage seat {seat_number} for {username}")
                return

            seat_off.click()
            self.handler.logger.info(
                f"Successfully removed occupant {souler_name_text} from seat {seat_number} by {username}")

    # ------------------------------------------------------------------
    # 占座与下麦（SeatingManager 合并进来）
    # ------------------------------------------------------------------
    async def sit_at_specific_seat(self, seat_number: int) -> dict:
        """Sit at a specific seat position (1-12) with viewport sync and page-source verification."""
        if self._foreign_seating is not None:
            return await self._foreign_seating.sit_at_specific_seat(seat_number)
        return await self._sit_at_specific_seat(seat_number)

    async def _sit_at_specific_seat(self, seat_number: int) -> dict:
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        if not 1 <= seat_number <= 12:
            return {'error': f'Invalid seat number {seat_number}. Must be between 1 and 12'}

        desk_index = (seat_number - 1) // 2
        row_index = desk_index // 2
        side = 'left' if seat_number % 2 == 1 else 'right'

        # 相位必须由本次真实滚动决定，不能只是声明：第二排（row 1）在展开后的
        # 默认可视区域内，但「默认视口就是顶相位」是没被真机证实过的假设 ——
        # 面板若停在滚动后的位置，带位偏移会算错。row 0/1 一律先滚到内容顶部
        # 夹住（row 1 时这次滚动被内容顶端夹住，是幂等的空操作），row 2 滚到底部。
        band = "bottom" if row_index == 2 else "top"
        scroll_target_desk = desk_index if row_index == 2 else 0

        try:
            # 展开座位面板
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            # 直达目标行滚动，传播对应相位
            self.scroll_to_row(scroll_target_desk, seat_desks)
            await asyncio.sleep(0.3)

            # 视口同步与 DOM 证据校验
            obs = self.observation
            observed = await obs.sync_current_viewport(band=band)
            if not observed or seat_number not in observed:
                return {'error': f'Seat {seat_number} could not be verified in viewport'}

            desk, seat_side, info = observed[seat_number]
            if info.get('occupied'):
                occupied_label = info.get("label") or info.get("username") or "occupant"
                return {'error': f'Seat {seat_number} is already occupied by {occupied_label}'}
            if not info.get('is_empty'):
                # occupied=False 且 is_empty=False 是第三种状态：读不到判据（渲染缺证据）。
                # 它同样不该点击，但不能谎报成「有人占座」。
                return {'error': f'Seat {seat_number} could not be verified in viewport'}

            # 目标为空座，通过 page_source 导出的坐标点击
            seat_element = obs._find_child_element(desk, f"{side}_seat")
            seat_bounds = getattr(seat_element, "bounds", None) if seat_element else None
            if seat_bounds and seat_bounds.get("width") and seat_bounds.get("height"):
                click_x = seat_bounds["x"] + seat_bounds["width"] // 2
                click_y = seat_bounds["y"] + seat_bounds["height"] // 2
            else:
                desk_bounds = getattr(desk, "bounds", None) or obs._desk_bounds(desk)
                if not desk_bounds or not desk_bounds.get("width") or not desk_bounds.get("height"):
                    return {'error': f'Could not determine click bounds for seat {seat_number}'}
                w, h = desk_bounds["width"], desk_bounds["height"]
                click_x = desk_bounds["x"] + (w // 4 if side == "left" else (3 * w) // 4)
                click_y = desk_bounds["y"] + h // 2

            gesture = getattr(self.handler, "gesture_handler", None)
            if not gesture or not hasattr(gesture, "click_at"):
                # 点不了就必须报错返回：继续往下走会去等一个不存在的确认弹窗
                return {'error': f'Gesture handler cannot click; seat {seat_number} was not selected'}
            gesture.click_at(click_x, click_y)
            await asyncio.sleep(0.3)

            # 确认就座
            result = self._confirm_seat()
            if result.get('success'):
                obs.mark_owner_seated(seat_number)
                self.current_desk_index = desk_index
                self.current_side = side

            return result

        except Exception as e:
            if hasattr(self.handler, "log_error"):
                self.handler.log_error(f"Error sitting at specific seat: {traceback.format_exc()}")
            return {'error': f'Failed to sit at seat {seat_number}: {str(e)}'}
        finally:
            try:
                await self.collapse_seats()
            except Exception as e:
                if hasattr(self.handler, "logger") and self.handler.logger:
                    self.handler.logger.error(f"Failed to collapse seats: {e}")

    async def find_owner_seat(self, force_relocate: bool = False) -> dict:
        """Find and take an available seat for owner"""
        if self._foreign_seating is not None:
            return await self._foreign_seating.find_owner_seat(force_relocate)
        return await self._find_owner_seat(force_relocate)

    async def _find_owner_seat(self, force_relocate: bool = False) -> dict:
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if self.current_desk_index >= len(seat_desks):
                self.current_desk_index = 0

            owner_position = self._get_owner_position(seat_desks)
            if owner_position:
                self.current_desk_index = owner_position['desk_index']
                self.current_side = owner_position['side']

                if owner_position['has_neighbor'] and not force_relocate:
                    self.handler.logger.info(
                        f"Owner already accompanying {owner_position['neighbor_label']} at desk {owner_position['desk_index'] + 1}"
                    )
                    return {'success': 'Owner already has a companion'}

            start_index = self.current_desk_index
            if owner_position:
                start_index = (owner_position['desk_index'] + 1) % len(seat_desks)

            scan_order = self._build_scan_order(len(seat_desks), start_index)
            first_empty_candidate = None

            for desk_index in scan_order:
                # Ensure the row containing this desk is visible
                self.scroll_to_row(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)
                # self.handler.logger.debug(f"desk_info: {desk_info}" )

                companion_candidate = self._select_companion_candidate(desk_info)
                if companion_candidate:
                    return self._take_seat(
                        desk_index,
                        companion_candidate['seat'],
                        neighbor_label=companion_candidate['neighbor_label']
                    )

                if not first_empty_candidate:
                    empty_candidate = self._select_empty_candidate(desk_info)
                    if empty_candidate:
                        first_empty_candidate = {
                            'desk_index': desk_index,
                            'seat': empty_candidate
                        }

            if first_empty_candidate:
                # Ensure the row containing the target seat is visible before taking it
                # This is important because we may have scrolled to other rows during scanning
                try:
                    self.scroll_to_row(first_empty_candidate['desk_index'], seat_desks)
                    # Re-collect desk info to get fresh element references after scrolling
                    desk = seat_desks[first_empty_candidate['desk_index']]
                    desk_info = self._collect_desk_info(desk)
                    # Update the seat element reference to ensure it's still valid
                    side = first_empty_candidate['seat']['side']
                    if side in desk_info and desk_info[side].get('element'):
                        first_empty_candidate['seat'] = desk_info[side]
                except Exception as e:
                    # If refreshing fails, log but continue with original candidate
                    self.handler.logger.warning(f"Failed to refresh seat element before taking seat: {str(e)}")

                return self._take_seat(
                    first_empty_candidate['desk_index'],
                    first_empty_candidate['seat']
                )

            return {'error': 'No available seats found'}

        except Exception as e:
            self.handler.log_error(f"Error finding seat: {traceback.format_exc()}")
            return {'error': f'Failed to find seat: {str(e)}'}

    async def accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        """Find a specific user on seats and sit next to them"""
        if self._foreign_seating is not None:
            return await self._foreign_seating.accompany_user(target_username, sender_username)
        return await self._accompany_user(target_username, sender_username)

    async def _accompany_user(self, target_username: str, sender_username: str = None) -> dict:
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Step 1: Check if the target user is online
            # Skip online check if sender is the target (they are obviously online).
            # 两侧名字可能来自不同命名域（调用方常拿到 DB 的主账号名，UI 只有分身名），
            # 所以同一身份必须按身份判定，而不是按字符串相等。
            from ushareiplay.dal.user_dao import UserDAO

            if not await UserDAO.is_same_identity(sender_username, target_username):
                info_manager = InfoManager.instance()
                if not await info_manager.is_user_or_avatar_online(target_username):
                    return {'error': f'User {target_username} is not online'}

            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            # Step 3: Iterate through all desks.
            # Optimization: only check desks with exactly one occupant, because
            # if both seats are occupied, we can't sit next to the target anyway.
            last_scrolled_row = -1
            for desk_index in range(len(seat_desks)):
                row_index = desk_index // 2
                if row_index != last_scrolled_row:
                    self.scroll_to_row(desk_index, seat_desks)
                    last_scrolled_row = row_index
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)

                left = desk_info['left']
                right = desk_info['right']
                occupied_sides = []
                if left.get('occupied'):
                    occupied_sides.append('left')
                if right.get('occupied'):
                    occupied_sides.append('right')

                # Only proceed when exactly one seat is occupied on this desk
                if len(occupied_sides) != 1:
                    continue

                side = occupied_sides[0]
                other_side = 'right' if side == 'left' else 'left'
                seat = desk_info[side]
                other_seat = desk_info[other_side]

                # Skip owner seat
                if seat.get('is_owner'):
                    continue

                seat_number = desk_index * 2 + (1 if side == 'left' else 2)

                # 点头像、读昵称、关掉弹窗整段交给 SeatPanelDriver：派对房间里一次盲按
                # back 就是退出派对房间，只有驱动才有资格按下那一次 back，而且必须
                # 在弹窗此刻确实还在屏幕上时才按。子系统自己不再碰任何弹窗动作。
                async with self.panel_driver.avatar_card(desk, side, seat_number) as card:
                    if card.opened:
                        self.handler.logger.info(
                            f"Checked {side} seat at desk {desk_index + 1} to check user"
                        )
                    actual_username = card.name

                # 读不到昵称＝没有可关的弹窗，也不是「不是那个人」，留给下一轮桌面
                if not actual_username:
                    self.handler.logger.warning(f"No user name found for {side} seat at desk {desk_index + 1}")
                    continue

                self.handler.logger.info(
                    f"Found user '{actual_username}' at desk {desk_index + 1}, {side} side"
                )

                # 麦位弹窗里是 Soul UI 的可见名字（分身名），调用方给的可能是主账号名：
                # 按身份匹配，命中后一律使用 UI 可见名字继续后续动作。
                if not await UserDAO.is_same_identity(target_username, actual_username):
                    # 不是目标：名片已由驱动按证据关掉，继续看下一张桌位
                    continue

                # 命中目标：名片同样已关好，接着检查旁边的麦位
                # Check if the adjacent seat is available
                if other_seat['occupied']:
                    return {'error': f'User {target_username} has no empty adjacent seat'}

                # Sit next to the target user
                self.handler.logger.info(
                    f"Sitting next to {actual_username} at desk {desk_index + 1}, {other_seat['side']} side"
                )

                # Re-collect desk info to get fresh element references after popup interaction
                desk_info = self._collect_desk_info(desk)
                fresh_other_seat = desk_info[other_side]

                return self._take_seat(
                    desk_index,
                    fresh_other_seat,
                    neighbor_label=actual_username
                )

            return {'error': f'User {target_username} not found on any seat'}

        except Exception as e:
            self.handler.log_error(f"Error accompanying user: {traceback.format_exc()}")
            return {'error': f'Failed to accompany user {target_username}: {str(e)}'}
        finally:
            try:
                await self.collapse_seats()
            except Exception as e:
                if hasattr(self.handler, "logger") and self.handler.logger:
                    self.handler.logger.error(f"Failed to collapse seats: {e}")

    async def seat_off_owner(self) -> dict:
        """Remove the owner from their current seat."""
        if self._foreign_seating is not None:
            return await self._foreign_seating.seat_off_owner()
        return await self._seat_off_owner()

    async def _seat_off_owner(self) -> dict:
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            for desk_index in range(len(seat_desks)):
                self.scroll_to_row(desk_index, seat_desks)
                desk = seat_desks[desk_index]
                desk_info = self._collect_desk_info(desk)

                for seat in (desk_info['left'], desk_info['right']):
                    if seat.get('is_owner') and seat.get('occupied'):
                        seat_number = desk_index * 2 + (1 if seat['side'] == 'left' else 2)
                        return self._seat_off(seat_number, seat)

            self.handler.logger.warning("Owner is not on any seat")
            return {'error': 'Owner is not on any seat'}

        except Exception as e:
            self.handler.log_error(f"Error removing owner from seat: {traceback.format_exc()}")
            return {'error': f'Failed to remove owner from seat: {str(e)}'}

    async def seat_off_specific_seat(self, seat_number: int) -> dict:
        """Remove the occupant from a specific seat position (1-12)."""
        if self._foreign_seating is not None:
            return await self._foreign_seating.seat_off_specific_seat(seat_number)
        return await self._seat_off_specific_seat(seat_number)

    async def _seat_off_specific_seat(self, seat_number: int) -> dict:
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            desk_index = (seat_number - 1) // 2
            side = 'left' if seat_number % 2 == 1 else 'right'

            seat_desks = await self.expand_and_find_desks()
            if not seat_desks:
                return {'error': 'Failed to find seat desks'}

            if desk_index >= len(seat_desks):
                return {'error': f'Desk {desk_index + 1} does not exist'}

            self.scroll_to_row(desk_index, seat_desks)
            desk = seat_desks[desk_index]
            desk_info = self._collect_desk_info(desk)
            target_seat = desk_info[side]

            if not target_seat.get('occupied'):
                return {'error': f'Seat {seat_number} is empty'}

            return self._seat_off(seat_number, target_seat)

        except Exception as e:
            self.handler.log_error(f"Error removing seat occupant: {traceback.format_exc()}")
            return {'error': f'Failed to remove occupant from seat {seat_number}: {str(e)}'}

    # ------------------------------------------------------------------
    # 占座内部读数
    # ------------------------------------------------------------------
    def _get_owner_position(self, seat_desks):
        for index, desk in enumerate(seat_desks):
            desk_info = self._collect_desk_info(desk)
            left = desk_info['left']
            right = desk_info['right']

            if left['is_owner']:
                has_neighbor = right['occupied'] and not right['is_owner']
                return {
                    'desk_index': index,
                    'side': 'left',
                    'has_neighbor': has_neighbor,
                    'neighbor_label': right['label'] if has_neighbor else ''
                }

            if right['is_owner']:
                has_neighbor = left['occupied'] and not left['is_owner']
                return {
                    'desk_index': index,
                    'side': 'right',
                    'has_neighbor': has_neighbor,
                    'neighbor_label': left['label'] if has_neighbor else ''
                }

        return None

    def _collect_desk_info(self, desk):
        left_seat = self.handler.element_finder.find_child_element(desk, 'left_seat', log_failure=False)
        right_seat = self.handler.element_finder.find_child_element(desk, 'right_seat', log_failure=False)
        left_state = self.handler.element_finder.find_child_element(desk, 'left_state', log_failure=False)
        right_state = self.handler.element_finder.find_child_element(desk, 'right_state', log_failure=False)
        left_label_element = self.handler.element_finder.find_child_element(desk, 'left_label', log_failure=False)
        right_label_element = self.handler.element_finder.find_child_element(desk, 'right_label', log_failure=False)

        left_label = left_label_element.text if left_label_element else ''
        right_label = right_label_element.text if right_label_element else ''

        return {
            'left': {
                'element': left_seat,
                'occupied': bool(left_state),
                'label': left_label,
                'is_owner': left_label == '群主',
                'side': 'left'
            },
            'right': {
                'element': right_seat,
                'occupied': bool(right_state),
                'label': right_label,
                'is_owner': right_label == '群主',
                'side': 'right'
            }
        }

    def _select_companion_candidate(self, desk_info):
        left = desk_info['left']
        right = desk_info['right']

        if right['element'] and left['occupied'] and not left['is_owner'] and not right['occupied']:
            return {'seat': right, 'neighbor_label': left['label'] or 'Unknown'}

        if left['element'] and right['occupied'] and not right['is_owner'] and not left['occupied']:
            return {'seat': left, 'neighbor_label': right['label'] or 'Unknown'}

        return None

    def _select_empty_candidate(self, desk_info):
        for seat in (desk_info['left'], desk_info['right']):
            if seat['element'] and not seat['occupied'] and not seat['is_owner']:
                return seat
        return None

    def _build_scan_order(self, total_count, start_index):
        return [(start_index + offset) % total_count for offset in range(total_count)]

    def _take_seat(self, desk_index, seat_info, neighbor_label=None):
        if self.handler is None or not seat_info or not seat_info.get('element'):
            return {'error': 'Seat element not available'}

        try:
            seat_info['element'].click()
            if neighbor_label:
                self.handler.logger.info(
                    f"Accompanying {neighbor_label} at desk {desk_index + 1}, {seat_info['side']} seat"
                )
            else:
                self.handler.logger.info(
                    f"Taking empty {seat_info['side']} seat at desk {desk_index + 1}"
                )

            result = self._confirm_seat()
            if result.get('success'):
                self.current_desk_index = desk_index
                self.current_side = seat_info['side']
            return result

        except Exception:
            self.handler.log_error(f"Error while clicking seat: {traceback.format_exc()}")
            return {'error': 'Failed to click seat'}

    def _seat_off(self, seat_number, seat_info):
        if self.handler is None or not seat_info or not seat_info.get('element'):
            return {'error': 'Seat element not available'}

        try:
            seat_info['element'].click()
            self.handler.logger.info(f"Clicked seat {seat_number} to remove occupant")

            seat_off = self.handler.element_finder.wait_for_element_clickable('seat_off')
            if not seat_off:
                self.handler.logger.error(f"Failed to find seat off button for seat {seat_number}")
                return {'error': f'Unable to manage seat {seat_number}'}

            found_key, souler_name = self.handler.element_finder.wait_for_any_element(['souler_name', 'user_name'])
            if not souler_name:
                self.handler.logger.error(f"No souler name found for seat {seat_number}")
                return {'error': f'Failed to verify occupant on seat {seat_number}'}

            souler_name_text = souler_name.text
            seat_off.click()
            self.handler.logger.info(f"Successfully removed {souler_name_text} from seat {seat_number}")
            return {'success': f'Successfully removed {souler_name_text} from seat {seat_number}'}

        except Exception:
            self.handler.log_error(f"Error while removing seat occupant: {traceback.format_exc()}")
            return {'error': 'Failed to remove seat occupant'}

    def _confirm_seat(self) -> dict:
        """Confirm seat selection"""
        if self.handler is None:
            return {'error': 'Handler not initialized'}

        try:
            # Wait for confirmation dialog
            confirm_button = self.handler.element_finder.wait_for_element_clickable('confirm_seat')
            if not confirm_button:
                self.handler.logger.error("Failed to find confirm button")
                return {'error': 'Failed to find confirm button'}

            confirm_button.click()
            self.handler.logger.info("Confirmed seat selection")
            bottom_drawer = self.handler.element_finder.wait_for_element_clickable('bottom_drawer')
            if bottom_drawer:
                self.handler.gesture_handler.click_element_at(bottom_drawer, 0.5, -0.1)
                self.handler.logger.info("Hide bottom drawer")
            return {'success': 'Successfully took a seat'}

        except Exception as e:
            self.handler.log_error(f"Error confirming seat: {traceback.format_exc()}")
            return {'error': f'Failed to confirm seat: {str(e)}'}


# 占座游标：SeatingManager 原本持有这两个状态，合并后归子系统所有，
# 旧句柄仍然通过属性读写同一份（见 seating.py）。
SeatSubsystem.current_desk_index = 0
SeatSubsystem.current_side = None