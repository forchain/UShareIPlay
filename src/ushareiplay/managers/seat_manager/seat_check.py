import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from ushareiplay.core.singleton import Singleton
from ushareiplay.dal import SeatReservationDAO, UserDAO
from ushareiplay.managers.seat_manager.seat_panel_driver import SeatPanelDriver
from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager


class SeatCheckManager(Singleton):
    def __init__(self, handler=None, seat_ui=None, panel_driver=None):
        self.handler = handler
        self.seat_ui = seat_ui if seat_ui is not None else (SeatUIManager.instance() if SeatUIManager.is_initialized() else None)
        self._panel_driver = panel_driver
        self._message_dispatch = None

    @property
    def panel_driver(self):
        """座位面板的 UI 驱动：点名片、读占座人昵称、按证据关弹窗。

        构造注入优先，缺省时按需自建并缓存。驱动刻意不是单例（它没有全局状态），
        所以接线层（#401）可以造一个共享实例传进来，调用点一行都不用改。
        """
        if self._panel_driver is None:
            self._panel_driver = SeatPanelDriver(self.handler)
        return self._panel_driver

    @property
    def message_dispatch(self):
        if self._message_dispatch is None:
            from ushareiplay.core.message_dispatch import MessageDispatch

            self._message_dispatch = MessageDispatch.instance().bind_handler(self.handler)
        return self._message_dispatch

    async def check_seats_on_entry(self, username: str = None):
        """Check seats when user enters the party"""
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

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """独占 UI 执行权，契约与 SeatObservationManager._ui_session 一致。

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

    async def check_user_specific_seat(self, username: str, seat_number: int):
        async with self._ui_session(f"seat_check:{seat_number}"):
            self.handler.logger.info("expanding seats for check")
            seat_desks = await self.seat_ui.expand_and_find_desks()
            if not seat_desks:
                return
            self.handler.logger.info(f"found {len(seat_desks)} seat desks")

            # check and handle the user's specific seat
            self.handler.logger.info(f"checking specific seat {seat_number} for user {username}")

            desk_index = (seat_number - 1) // 2
            self.seat_ui.scroll_to_row(desk_index, seat_desks, duration=1000)
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
