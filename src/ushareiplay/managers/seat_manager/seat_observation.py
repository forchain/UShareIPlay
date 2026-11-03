from __future__ import annotations

import asyncio
import logging
import re
import traceback
from contextlib import asynccontextmanager
from typing import ClassVar, Dict, List, Optional, Set, Tuple

from lxml import etree

from ushareiplay.core.config_view import Locator
from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.seat_manager.seat_ledger import (
    SeatLedger,
    SeatObservationGateState,
    SeatRescanCooldownPolicy,
    SeatSlot,
    claimed_usernames,
    evidence_weight,
)
from ushareiplay.managers.seat_manager.seat_panel_reader import SeatPanelReader

# 专注人数文案：主形态「7人专注中」，兜底取任意数字（文案变形时不至于整个读不到）。
# 事件链路与观测器的按需读共用这一份判法，两边对同一个界面的读数才不会打架。
_FOCUS_COUNT_PATTERN = re.compile(r"(\d+)人专注中")
_FOCUS_COUNT_FALLBACK_PATTERN = re.compile(r"(\d+)")


def parse_focus_count_text(text: Optional[str]) -> Optional[int]:
    """从 tvStudyRoomDesc 的文案里解析专注人数；读不出数字返回 None。"""
    if not text:
        return None
    match = _FOCUS_COUNT_PATTERN.search(text) or _FOCUS_COUNT_FALLBACK_PATTERN.search(text)
    return int(match.group(1)) if match else None


class SeatObservationManager(Singleton):
    """
    负责麦位被动观测、全量 12 麦位状态维护、3 排视觉快照日志输出、
    以及专注人数与可视麦位背离时的自动展开探测。
    """

    MIN_INTERACTABLE_DESK_HEIGHT: ClassVar[int] = 100

    # AvatarView 里的头像图片节点：空座恰好一张占位图，占座是头像 + 挂件/边框。
    # 这是 Android 框架的类名，不是目标 App 的选择器（App 改版不会动它），
    # 所以按框架常量放在这里，不进 config.yaml 的 elements。
    IMAGE_VIEW_CLASS: ClassVar[str] = "android.widget.ImageView"

    # 空座占位文案：出现它们就说明这一侧没人
    EMPTY_SEAT_LABELS: ClassVar[Tuple[str, ...]] = ("点击入座", "入座")

    # 座次表着色：在座亮青加粗、本轮变更亮绿加粗、空闲压暗。消息体自带转义码，
    # 文件日志那份由 ColoredFormatter(use_colors=False) 剥离，两边内容逐字一致。
    SEAT_COLOR_OCCUPIED: ClassVar[str] = "\033[1;36m"
    SEAT_COLOR_CHANGED: ClassVar[str] = "\033[1;32m"
    SEAT_COLOR_IDLE: ClassVar[str] = "\033[90m"
    SEAT_COLOR_RESET: ClassVar[str] = "\033[0m"

    def __init__(
        self,
        handler=None,
        seat_ui=None,
        cooldown_policy: Optional[SeatRescanCooldownPolicy] = None,
        gate_state: Optional[SeatObservationGateState] = None,
        panel_reader: Optional[SeatPanelReader] = None,
    ):
        self.handler = handler
        self._logger = None
        self._controller = None
        self._seat_ui = seat_ui
        self._panel_reader = panel_reader
        # 12 个号位的状态与策略都在账本里；本类只做 UI 协调与日志。
        self.ledger = SeatLedger(
            cooldown_policy=cooldown_policy,
            gate_state=gate_state,
            logger=self.logger,
            owner_nickname=self._owner_nickname,
            is_room_admin=self._admin_manager_has,
            record_room_admin=self._admin_manager_add,
        )

    @property
    def seats(self) -> Dict[int, SeatSlot]:
        """兼容旧调用方的活快照字典；只读新代码请用 `snapshot()`。"""
        return self.ledger.slots

    @property
    def gate_state(self) -> SeatObservationGateState:
        return self.ledger.gate_state

    @property
    def cooldown_policy(self) -> SeatRescanCooldownPolicy:
        return self.ledger.cooldown_policy

    @cooldown_policy.setter
    def cooldown_policy(self, val: SeatRescanCooldownPolicy):
        self.ledger.cooldown_policy = val

    # 旧属性兼容：测试与少量调用方仍按旧名字读写账本闸门。
    @property
    def _last_focus_count(self) -> Optional[int]:
        return self.gate_state.last_focus_count

    @_last_focus_count.setter
    def _last_focus_count(self, val: Optional[int]):
        self.gate_state.last_focus_count = val

    @property
    def _reconciled_focus_count(self) -> Optional[int]:
        return self.gate_state.reconciled_focus_count

    @_reconciled_focus_count.setter
    def _reconciled_focus_count(self, val: Optional[int]):
        self.gate_state.reconciled_focus_count = val

    @property
    def _scanned_seat_change_fingerprint(self) -> Optional[frozenset]:
        return self.gate_state.scanned_seat_change_fingerprint

    @_scanned_seat_change_fingerprint.setter
    def _scanned_seat_change_fingerprint(self, val: Optional[frozenset]):
        self.gate_state.scanned_seat_change_fingerprint = val

    @property
    def _last_rescan_ok(self) -> bool:
        return self.gate_state.last_rescan_ok

    @_last_rescan_ok.setter
    def _last_rescan_ok(self, val: bool):
        self.gate_state.last_rescan_ok = val

    @property
    def _last_rescan_time(self) -> float:
        return self.gate_state.last_rescan_time

    @_last_rescan_time.setter
    def _last_rescan_time(self, val: float):
        self.gate_state.last_rescan_time = val

    @property
    def _last_visible_band(self) -> Optional[Tuple]:
        return self.gate_state.last_visible_band

    @_last_visible_band.setter
    def _last_visible_band(self, val: Optional[Tuple]):
        self.gate_state.last_visible_band = val

    @property
    def _band_change_reason(self) -> Optional[str]:
        return self.gate_state.band_change_reason

    @_band_change_reason.setter
    def _band_change_reason(self, val: Optional[str]):
        self.gate_state.band_change_reason = val

    @property
    def _residual_seats(self) -> Dict[int, str]:
        return self.gate_state.residual_seats

    @_residual_seats.setter
    def _residual_seats(self, val: Dict[int, str]):
        self.gate_state.residual_seats = val

    @property
    def _residual_seats_inspected_at(self) -> Dict[int, float]:
        return self.gate_state.residual_seats_inspected_at

    @_residual_seats_inspected_at.setter
    def _residual_seats_inspected_at(self, val: Dict[int, float]):
        self.gate_state.residual_seats_inspected_at = val

    @property
    def _unknown_identity_probed_at(self) -> Dict[int, float]:
        return self.gate_state.unknown_identity_probed_at

    @_unknown_identity_probed_at.setter
    def _unknown_identity_probed_at(self, val: Dict[int, float]):
        self.gate_state.unknown_identity_probed_at = val

    @property
    def _last_scan_fingerprint(self) -> Optional[frozenset]:
        return self.gate_state.last_scan_fingerprint

    @_last_scan_fingerprint.setter
    def _last_scan_fingerprint(self, val: Optional[frozenset]):
        self.gate_state.last_scan_fingerprint = val

    @property
    def _consistency_retry_due(self) -> bool:
        return self.gate_state.consistency_retry_due

    @_consistency_retry_due.setter
    def _consistency_retry_due(self, val: bool):
        self.gate_state.consistency_retry_due = val

    @property
    def _lock(self) -> asyncio.Lock:
        return self.gate_state.lock

    @_lock.setter
    def _lock(self, val: asyncio.Lock):
        self.gate_state.lock = val

    def bind_handler(self, handler):
        if handler:
            self.handler = handler
            if self._panel_reader is not None:
                self._panel_reader.handler = handler
            if self._seat_ui:
                self._seat_ui.handler = handler
            if hasattr(self.handler, "logger") and self.handler.logger:
                self._logger = self.handler.logger
            if hasattr(self.handler, "controller") and self.handler.controller:
                self._controller = self.handler.controller
            self.ledger.logger = self.logger
        return self

    def _admin_manager_has(self, username: str) -> bool:
        """外部管理员登记（AdminManager）查询；账本自己的麦位证据由账本判。"""
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            return AdminManager.is_initialized() and AdminManager.instance().is_room_admin(username)
        except Exception:
            return False

    def _admin_manager_add(self, username: str) -> None:
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            if AdminManager.is_initialized():
                AdminManager.instance().add_room_admin(username)
        except Exception:
            pass

    @property
    def panel_reader(self) -> SeatPanelReader:
        """座位面板唯一读数器。注入优先，缺省按需自建。"""
        if self._panel_reader is None:
            self._panel_reader = SeatPanelReader(self.handler)
        elif self.handler and self._panel_reader.handler is not self.handler:
            self._panel_reader.handler = self.handler
        return self._panel_reader

    @property
    def logger(self):
        if self._logger is None:
            if self.handler and hasattr(self.handler, "logger") and self.handler.logger:
                self._logger = self.handler.logger
            else:
                self._logger = logging.getLogger("ushareiplay.seat_observation")
        return self._logger

    @property
    def controller(self):
        if self._controller is None and self.handler:
            self._controller = getattr(self.handler, "controller", None)
        return self._controller

    @property
    def seat_ui(self):
        """面板委派；没有注入时为 None，扫描路径的 hasattr 守卫会跳过面板动作。

        委派一律由接线层显式注入（app_controller 传 `SeatSubsystem.panel`）：
        观测器与子系统必须共用同一份面板实现，回退去别处解析会得到第二份。
        """
        return self._seat_ui

    def clear(self):
        """重置所有麦位状态与决策闸门状态"""
        self.ledger.clear()
        self.logger.info("Cleared seat observation snapshot")

    def read_focus_count_from_ui(self) -> Optional[int]:
        """按需读一次界面上的专注人数（tvStudyRoomDesc「N人专注中」）。

        人数的缓存（`_last_focus_count` / `RoomState.focus_count`）**只由事件流
        被动写入**，而 FocusCountEvent 在「人数没变」时直接早退。冷启动进房、
        `RoomState.clear()` 之后、或 seat 事件先于 focus_count 事件到达时，缓存
        就是空的 —— 于是日志打「专注人数: 未知」，更要命的是
        `_verify_focus_consistency` 拿到 None 直接 return，唯一一次对账整个跳过
        （真机 10-10 01:49:30~01:50:32：连扫 4~5 遍、零次座位更新，每行都写着未知）。

        这个数字**一直在屏幕上**，是判断「这遍扫对没有」的唯一硬依据，所以允许
        直接读。调用方必须已持有 ui_session —— 这是同步 driver 调用，与点头像
        读弹窗同一类 UI 动作，无锁裸调会和 EventManager 的兜底 back 撞车。

        读不到就返回 None：宁可继续显示「未知」，也不猜一个数去污染对账。
        """
        finder = getattr(self.handler, "element_finder", None)
        if finder is None or not hasattr(finder, "try_find_element"):
            return None
        try:
            element = finder.try_find_element("focus_count", log=False)
        except Exception as e:
            self.logger.debug(f"Failed to read focus count from UI: {e}")
            return None
        if element is None:
            return None
        return parse_focus_count_text(getattr(element, "text", ""))

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """独占 UI 执行权，委托给 reader.session。"""
        async with self.panel_reader.session(reason):
            yield

    def _find_child_element(self, desk, element_key: str):
        return self.panel_reader.find_child_element(desk, element_key)

    def _element_locator(self, element_key: str) -> Optional[Locator]:
        return self.panel_reader._element_locator(element_key)

    def _avatar_image_count(self, desk, side: str) -> int:
        return self.panel_reader._avatar_image_count(desk, side)

    def _get_label_text(self, desk, side: str) -> str:
        return self.panel_reader._get_label_text(desk, side)

    @staticmethod
    def _is_seat_number_label(label: str) -> bool:
        return SeatPanelReader._is_seat_number_label(label)

    def format_3row_layout(
        self,
        trigger_source: str = "可视区域变更",
        focus_count: Optional[int] = None,
        changed_seats: Optional[Set[int]] = None,
    ) -> str:
        """
        输出符合物理现实效果的直观快照：一排两张桌，每张桌两个人，共三排。
        输出专注人数（与在座人数一致）。

        changed_seats 是本轮真的动了的号位（着色用），不参与文本内容 —— 同一份文本
        在有/无颜色的两个 sink 上必须逐字一致（文件日志的转义码由 ColoredFormatter 剥离）。
        """
        if focus_count is None:
            focus_count = self._last_focus_count
        if focus_count is None:
            try:
                from ushareiplay.state.room_state import RoomState
                focus_count = RoomState.instance().focus_count
            except Exception:
                pass
        focus_str = str(focus_count) if focus_count is not None else "未知"
        changed_seats = changed_seats or set()

        room_admins = set()
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            if AdminManager.is_initialized():
                room_admins = AdminManager.instance().get_room_admins()
        except Exception:
            pass

        def format_seat(num: int) -> str:
            slot = self.seats.get(num)
            if not slot or not slot.occupied:
                return f"{self.SEAT_COLOR_IDLE}[{num}号: 空闲]{self.SEAT_COLOR_RESET}"
            if slot.is_owner:
                name = f"群主({slot.username})" if slot.username and slot.username != "群主" else "群主"
            else:
                is_admin = (slot.username in room_admins) if slot.username else False
                if not is_admin and (slot.label == "管理" or self.ledger.is_known_room_admin(slot.username)):
                    is_admin = True
                    if slot.username:
                        self.ledger.record_room_admin(slot.username)


                if is_admin:
                    name = f"管理({slot.username})" if slot.username and slot.username != "管理" else "管理"
                else:
                    name = slot.username or slot.label or "已占用"
            color = self.SEAT_COLOR_CHANGED if num in changed_seats else self.SEAT_COLOR_OCCUPIED
            return f"{color}[{num}号: {name}]{self.SEAT_COLOR_RESET}"

        lines = [
            f"[FocusSeatObservation] 专注麦位状态变更 (触发源: {trigger_source}, 专注人数: {focus_str}):",
            f"  第一排: {format_seat(1)} {format_seat(2)}  |  {format_seat(3)} {format_seat(4)}",
            f"  第二排: {format_seat(5)} {format_seat(6)}  |  {format_seat(7)} {format_seat(8)}",
            f"  第三排: {format_seat(9)} {format_seat(10)}  |  {format_seat(11)} {format_seat(12)}",
        ]
        return "\n".join(lines)

    def get_user_seat(self, username: str) -> Optional[int]:
        """查询用户当前所占座位号（1..12），若不在座位上则返回 None。"""
        return self.ledger.get_user_seat(username)

    def get_all_seated_users(self) -> Dict[str, int]:
        """返回当前所有在座用户及其座位号映射 {username: seat_number}。"""
        return self.ledger.get_all_seated_users()

    def map_desks_to_indices(self, desk_wrappers: list) -> List[Tuple[int, any]]:
        """
        把当前可见的 desk_wrappers 映射为其全局 desk_index (0..5)。
        - Row 0 (第一排): desk 0 (seats 1,2), desk 1 (seats 3,4)
        - Row 1 (第二排): desk 2 (seats 5,6), desk 3 (seats 7,8)
        - Row 2 (第三排): desk 4 (seats 9,10), desk 5 (seats 11,12)

        座位号只认麦位编号锚点：某张桌位自己读到编号，或同一视口里其它桌位读到编号、
        由此推定整条带位的偏移。读不到编号的桌位身份未知，一律不映射 —— 宁可不写，
        不可猜。旧实现在无锚点时「从 desk 0 起往后再排」，面板被滚动、只露出中后排
        时会把整条带位整体错配（第二排的读数被写进 1~4 号位），这正是把 3 号位
        已确认占座推平的那次死循环的机理。
        """
        mapped, _dropped, _source = self._map_desks_with_identity(desk_wrappers)
        return [(desk_idx, desk) for desk_idx, desk, _own in mapped]

    def _map_desks_with_identity(
        self, desk_wrappers: list, *, band: Optional[str] = None
    ) -> Tuple[List[Tuple[int, any, bool]], List[Tuple[any, str]], str]:
        """映射可见桌位，并标注座位号是不是这张桌位自己读出来的。

        Args:
            band: 已知滚动相位（"top"/"bottom"，仅展开重扫路径传入）。相位成立时
                不依赖数字 label 锚点也能定座位号，见 _band_offset_from_phase。

        Returns:
            mapped: [(desk_index, desk, own_seat_number)]，按 desk_index 升序。
                own_seat_number=True 表示这张桌位自己读到了麦位编号（自己钉死座位号）；
                False 表示座位号是由同视口其它桌位的编号推定的（带位整体可信，但
                单张桌位仍有错位可能）。
            dropped: [(desk, 原因)]，身份未知或不可见的桌位，调用方不得写快照。
            offset_source: 带位偏移的来源说明（诊断用）。
        """
        # 过滤掉不产出麦位数据的桌位（底座残片 / 没渲染出麦位 DOM 的空容器）
        visible_desks = []
        dropped: List[Tuple[any, str]] = []
        for desk in desk_wrappers:
            if self._is_desk_visible(desk):
                visible_desks.append(desk)
            else:
                dropped.append((desk, "无麦位 DOM（底座残片或未渲染）"))
        if not visible_desks:
            return [], dropped, "无可见桌位"

        # 视觉顺序（先按 y 量化分行、再按 x）就是带位里的连续序号
        ordered = sorted(visible_desks, key=self._desk_sort_key)

        anchored: Dict[int, int] = {}
        for rank, desk in enumerate(ordered):
            desk_idx = self._detect_desk_index_from_labels(desk)
            if desk_idx is not None and 0 <= desk_idx <= 5:
                anchored[rank] = desk_idx

        offsets = {idx - rank for rank, idx in anchored.items()}
        if len(offsets) == 1:
            # 锚点唯一确定了整条带位的偏移：只露出一排的视口也能对上正确座位号
            offset: Optional[int] = offsets.pop()
            offset_source = f"锚定({offset})"
        else:
            # 锚点缺失/矛盾时用已知滚动相位兜底（只有重扫路径给得出相位），
            # 相位也不成立就整条带位身份未知，只保留自身读到编号的桌位
            phase_offset = self._band_offset_from_phase(ordered, band, dropped)
            if phase_offset is not None:
                offset = phase_offset
                offset_source = f"相位({band})"
            else:
                offset = None
                offset_source = "锚点矛盾" if offsets else "锚点缺失"

        mapped: List[Tuple[int, any, bool]] = []
        for rank, desk in enumerate(ordered):
            desk_idx = anchored.get(rank)
            own_seat_number = desk_idx is not None
            if desk_idx is None:
                if offset is None:
                    dropped.append((desk, "身份未知（无锚点）"))
                    continue
                desk_idx = offset + rank
                if not 0 <= desk_idx <= 5:
                    dropped.append((desk, f"推定座位号越界({desk_idx})"))
                    continue
            if band == "top" and desk_idx > 3:
                dropped.append((desk, f"超出顶相位视口(desk_idx={desk_idx})"))
                continue
            if band == "bottom" and desk_idx < 2:
                dropped.append((desk, f"超出底相位视口(desk_idx={desk_idx})"))
                continue
            mapped.append((desk_idx, desk, own_seat_number))

        mapped.sort(key=lambda item: item[0])
        return mapped, dropped, offset_source

    def _band_offset_from_phase(
        self, ordered: List[any], band: Optional[str], dropped: List[Tuple[any, str]]
    ) -> Optional[int]:
        """按已确认的滚动相位推出整条带位的偏移（不需要数字 label 锚点）。

        展开重扫的两次读数由本管理器自己把面板滚到两端后采集（见
        _scan_all_rows_expanded）：顶相位 scroll_to_row(0) 会被滚到内容顶部夹住，
        可见带位一定从第一排（desk 0）起；底相位 scroll_to_row(4) 被滚到底部夹住，
        一定到第三排（desk 5）止。房间里的 label 只在普通用户占座时才是数字
        （config.yaml：群主/管理占座显示身份文字、空座没有 label 节点），
        光靠锚点会让「第二排只露一角 + 群主占座」的视口整屏读不出任何座位号。

        仍然做几何校验：顶相位要求可见带位上方没有任何有坐标的桌位节点（含被裁掉
        的残片），底相位要求下方没有 —— 滚动失败时读数会错位，宁可不写不可猜。
        """
        if band not in ("top", "bottom") or not ordered:
            return None

        first_key = self._desk_sort_key(ordered[0])
        last_key = self._desk_sort_key(ordered[-1])
        fragment_keys = [
            self._desk_sort_key(desk)
            for desk, _reason in dropped
            if self._desk_bounds(desk) is not None
        ]

        if band == "top":
            if any(key < first_key for key in fragment_keys):
                return None
            return 0
        if any(key > last_key for key in fragment_keys):
            return None
        return 6 - len(ordered)

    def _desk_sort_key(self, desk) -> Tuple[int, int]:
        bounds = getattr(desk, "bounds", None)
        if isinstance(bounds, dict):
            # 将 y 按 40px 进行量化，形成同一行的行优先排序
            row_y = (bounds.get("y", 0) // 40) * 40
            x = bounds.get("x", 0)
            return (row_y, x)
        loc = getattr(desk, "location", None)
        if isinstance(loc, dict):
            row_y = (loc.get("y", 0) // 40) * 40
            x = loc.get("x", 0)
            return (row_y, x)
        return (0, 0)

    # 麦位编号的左右奇偶约定（config.yaml 中 left_label/right_label 注释：
    # 左侧 1,3,5,7,9,11；右侧 2,4,6,8,10,12）
    _SIDE_SEAT_PARITY: ClassVar[Dict[str, int]] = {"left": 1, "right": 0}

    def _label_seat_number(self, desk, side: str) -> Optional[int]:
        """label 整段是 1~12 的纯数字时返回该数字，否则 None。

        房间里只有空座位显示编号，占座后 label 换成昵称/群主/管理，所以带数字的
        昵称（「小明7」）不算；纯数字昵称的误读由下面的奇偶/配对校验兜住。
        """
        label_text = self._get_label_text(desk, side).strip()
        if not self._is_seat_number_label(label_text):
            return None
        return int(label_text)

    def _seat_number_from_label(self, desk, side: str) -> Optional[int]:
        """单侧读到的编号，需符合左右奇偶约定。"""
        seat_num = self._label_seat_number(desk, side)
        if seat_num is None or seat_num % 2 != self._SIDE_SEAT_PARITY[side]:
            return None
        return seat_num

    def _detect_desk_index_from_labels(self, desk) -> Optional[int]:
        left_raw = self._label_seat_number(desk, "left")
        right_raw = self._label_seat_number(desk, "right")

        if left_raw is not None and right_raw is not None:
            # 两侧都是编号时必须构成一张桌子（左奇 + 右=左+1），
            # 否则说明其中一个是纯数字昵称，整张桌子都不锚定。
            if left_raw % 2 == 0 or right_raw != left_raw + 1:
                return None
            return (left_raw - 1) // 2

        seat_num = self._seat_number_from_label(desk, "left")
        if seat_num is None:
            seat_num = self._seat_number_from_label(desk, "right")
        if seat_num is None:
            return None
        return (seat_num - 1) // 2

    def room_owner_nickname(self) -> Optional[str]:
        """观测器认出的房主昵称（读不到就是 None）。

        「群主」身份文字 → 配置的房主昵称；认不出时返回 None，调用方保留「群主」。
        """
        return self._owner_nickname()

    def _owner_nickname(self) -> Optional[str]:
        """「群主」身份文字 → 配置的房主昵称；认不出时返回 None，调用方保留「群主」。

        label 读到「群主」的座位和弹窗在别处读到的房主昵称是同一个人：身份不归一，
        「一人一麦位」闸（_claimed_usernames / _resolve_usernames 按字符串比对）
        对房主的重复登记完全失明（真机 09-28 18:07:28：[9号: Joyer] + [11号: 群主]，
        同一个人占两座，专注 1 人对着两个人打架）。
        只认显式配置：别人的房间里「群主」徽章是那位群主，绝不能套自己配的房主。
        """
        try:
            from ushareiplay.state.room_state import RoomState
            if RoomState.instance().is_guest_room:
                return None
        except Exception:
            pass
        try:
            from ushareiplay.core.roles import RolePolicy
            cfg = getattr(self.handler, "config", None)
            if cfg is None:
                return None
            return RolePolicy(cfg).configured_room_owner or None
        except Exception:
            return None

    def _extract_seat_info(self, desk, side: str, seat_num: Optional[int] = None) -> dict:
        reading = self.panel_reader.read(desk, side, seat_number=seat_num)
        label = reading.label

        is_owner = (label == "群主")
        username = None
        if is_owner:
            username = self._owner_nickname() or "群主"
        # 这里问的是「label 能不能当昵称用」，与 reading.occupied 问的
        # 「label 是不是占座证据」是两个问题：管理/已占用是占座证据但不是昵称。
        elif label and not label.isdigit() and label not in ("管理", "已占用", "点击入座"):
            username = label

        return {
            "occupied": reading.occupied,
            "is_empty": reading.is_empty,
            "label": label,
            "is_owner": is_owner,
            "username": username,
            "has_state": reading.has_state,
            "has_default": reading.has_default,
            "has_rank": reading.has_rank,
            "avatar_images": reading.avatar_images,
        }

    def _desk_bounds(self, desk) -> Optional[dict]:
        """desk 的屏幕坐标（ElementWrapper 给 bounds，raw WebElement 给 location/size）。"""
        return self.panel_reader._desk_bounds(desk)

    def _has_desk_content(self, desk) -> bool:
        """桌位是否有任何麦位 DOM 证据（占座、麦位标签、空座占位）。

        底座残片（bgRoot + left/rightBottomView，没有 left/rightUserView）靠
        「一条结构证据都不成立」识别，而不是去认底座节点本身：任意一侧渲染出
        userView 里的东西（头像图、ClState、标签、占位文案）就说明这张桌位在
        产出麦位数据。这样无需给底座节点另配选择器，也不会把「露出了底座、
        同时又露出某个麦位」的桌位误杀（见 #341）。
        """
        if desk is None:
            return False
        for side in ("left", "right"):
            reading = self.panel_reader.read(desk, side)
            if reading.occupied or reading.is_empty or reading.label.strip():
                return True
        return False

    def _is_desk_interactable(self, desk) -> bool:
        """桌位是否在当前视口具备足够的可点击交互高度。

        DOM 读取（_is_desk_visible）不限高度（Android 会 dump 残片节点的 DOM），
        但点头像弹窗必须依赖屏幕真实渲染区域。完整桌位高约 200px（头像高 167px
        且上边距约 50px），低于阈值的残片桌位（真机 10~56px）头像已被视口裁切，
        按中心点击只会击中视口边缘外的空白或装饰边框，必然导致弹窗失败和超时报错。

        读不出 bounds（既没有 bounds 属性，也没有 location/size）同样判为不可交互：
        渲染尺寸未知就无法证明它在视口内，与「绝不盲目点击」同源 —— 宁可这一轮
        不点头像（身份留空交给下一轮），也不在未知坐标上盲点（见 #450）。
        """
        bounds = self._desk_bounds(desk)
        if not bounds:
            return False
        w = bounds.get("width", 0)
        h = bounds.get("height", 0)
        if h < self.MIN_INTERACTABLE_DESK_HEIGHT:
            return False
        if w > 0 and (h / w) < 0.4:
            return False
        return True

    def _is_desk_visible(self, desk) -> bool:
        """桌位是否可用作麦位读数 —— 只由 DOM 决定。

        像素宽高阈值（旧 FULL_DESK_MIN_HEIGHT=120 与 <60px 残片过滤）已删除
        （见 #341）：Android 的无障碍层会把「哪怕只露出一部分」的 View 完整 dump
        进 page source，几十像素高不代表读不到，所以高度不能当可见性的代理。
        """
        if desk is None:
            return False
        if hasattr(desk, "is_displayed"):
            try:
                if not desk.is_displayed():
                    return False
            except Exception:
                pass
        return self._has_desk_content(desk)

    def _click_seat_avatar(self, desk, side: str, target_element) -> bool:
        """点开麦位头像弹窗。

        raw WebElement 直接点；ElementWrapper 的 click() 取不到真实元素（子元素
        wrapper 没有 element key，get_web_element() 返回 None 且静默 False），
        所以退回按 bounds 坐标点击。
        """
        if not self._is_desk_interactable(desk):
            return False

        if target_element is not None and not isinstance(target_element, ElementWrapper):
            try:
                target_element.click()
                return True
            except Exception:
                pass

        pt = self.panel_reader.tap_point(desk, side)
        if pt is None:
            return False
        x, y = pt

        gesture = getattr(self.handler, "gesture_handler", None)
        if gesture is None or not hasattr(gesture, "click_at"):
            return False
        return bool(gesture.click_at(x, y))

    # 麦位头像弹窗开着的证据：弹窗自己渲染的昵称节点（两种名片各一套 id）。
    # 与房间档案模块的 DIALOG_KEYS 同一套判法：节点在 dump 里才说明弹窗开着。
    SEAT_CARD_EVIDENCE_KEYS = ("souler_name", "user_name")

    def _seat_card_still_present(self) -> bool:
        """头像名片此刻是否还在屏幕上 —— 关它的那次 back 只能由这个证据授权。

        反过来说：拿不到证据就绝不按 back。房间界面上的一次盲按 back 就是退出
        派对房间（`RoomProfileManager.ensure_closed` 记过同一笔账）。
        """
        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return False
        for key in self.SEAT_CARD_EVIDENCE_KEYS:
            try:
                if finder.try_find_element(key, log=False):
                    return True
            except Exception:
                continue
        return False

    async def inspect_occupant(self, desk, side: str, seat_number: int) -> Optional[str]:
        """点击麦位弹窗读取用户昵称；只有弹窗真的开了才按 back 关它。

        点名由「占座但身份未知」触发，而被点名的位子未必真有可点的头像：房主换座后
        旧位子会留下残留渲染（真机 09-28 18:07/20:46 的 9 号位），面板又常常是收起
        状态，按快照坐标点出去可能什么都没打开。房间里的一次盲按 back 就是退出派对
        房间（见 `RoomProfileManager.ensure_closed` 的同款告诫），所以 back 必须由证据授权：
        读到昵称节点才算弹窗开着；点都没点出去时同样不按。读不到昵称的弹窗不在屏幕上
        的可能性远大于它就是房间本身 —— 宁可留「身份未知」给下一轮，不可拿房间去赌。
        """
        if not self.handler:
            return None

        self.logger.info(f"Inspecting occupant on seat {seat_number} ({side} side)")
        popup_open = False
        try:
            target_element = self._find_child_element(desk, f"{side}_state")
            if target_element is None:
                target_element = self._find_child_element(desk, f"{side}_seat")
            if not self._click_seat_avatar(desk, side, target_element):
                self.logger.warning(
                    f"Seat {seat_number} ({side} side): avatar tap never landed "
                    f"(no bounds / gesture failed); nothing to close"
                )
                return None

            await asyncio.sleep(0.3)

            username = None
            if hasattr(self.handler, "element_finder"):
                _found_key, name_elem = self.handler.element_finder.wait_for_any_element(
                    list(self.SEAT_CARD_EVIDENCE_KEYS), timeout=1.5
                )
                popup_open = name_elem is not None
                if name_elem and hasattr(name_elem, "text") and name_elem.text:
                    username = name_elem.text.strip()

            if not popup_open:
                # 超时不等于没开：卡片可能刚过 1.5s 才渲染出来。留在屏幕上的卡片
                # 会挡住后面的麦位读数，甚至被下一个号位读成自己的占座人。
                popup_open = self._seat_card_still_present()

            return username

        except Exception as e:
            self.logger.error(f"Error inspecting occupant on seat {seat_number}: {e}")
            return None
        finally:
            try:
                if popup_open and hasattr(self.handler, "key_actions"):
                    self.handler.key_actions.press_back()
                await asyncio.sleep(0.2)
            except Exception:
                pass

    def _visible_band_signature(self, desk_wrappers: list) -> Optional[Tuple]:
        """可见麦位带的内容指纹（只记读数，不含座位号），用于身份未知时的变更检测。

        只收 DOM 读数（label 原文、头像图数、ClState/占位文案/段位图标的有无），
        不含屏幕坐标：面板被滚动（同一批读数换了位置）不算变更，读数本身变了才算。
        """
        rows = []
        for desk in sorted(desk_wrappers or [], key=self._desk_sort_key):
            if not self._has_desk_content(desk):
                continue
            sides = []
            for side in ("left", "right"):
                reading = self.panel_reader.read(desk, side)
                sides.append(
                    (
                        reading.label.strip(),
                        int(reading.avatar_images),
                        bool(reading.has_state),
                        bool(reading.has_default),
                        bool(reading.has_rank),
                    )
                )
            rows.append(tuple(sides))
        return tuple(rows) if rows else None

    def _visible_band_geometry_key(self, desk_wrappers: list) -> Optional[Tuple]:
        """可见麦位带的屏形状（桌位节点的排布），内容指纹的比对前提。

        麦位带的内容只有在「同一屏形状」之间才可比：面板展开/收起、滚动位置一变，
        可见桌位的数量与坐标就全变了，拿两份不同形状的读数比内容只会造出假变更
        —— 那正是旧版在身份可解析轮次直接清空基线的原因（见 _read_band_baseline）。
        """
        keys = tuple(
            self._desk_sort_key(desk)
            for desk in sorted(desk_wrappers or [], key=self._desk_sort_key)
            if self._has_desk_content(desk)
        )
        return keys or None

    def _read_band_baseline(self, desk_wrappers: list) -> Tuple:
        """刷新麦位带基线并返回 (上一轮基线, 本轮形状, 本轮内容)。

        每一轮都刷新，身份可解析的轮次也不例外：把唯一编号 label 带走的正是换座本身
        （人离座后那个位子只剩「点击入座」），下一轮往往就再也读不出座位号了。基线
        一旦在这里被清空，这次变更就永远没有可比对象 —— 真机「可视范围内换座没有
        检测到座位变化」的漏检就是这么来的。
        """
        geometry = self._visible_band_geometry_key(desk_wrappers)
        signature = self._visible_band_signature(desk_wrappers)
        previous = self._last_visible_band
        if signature is not None:
            self._last_visible_band = (geometry, signature)
        return previous, geometry, signature

    def _note_band_change(self, desk_wrappers: list) -> None:
        """身份未知时比对可见带内容指纹，变了就登记一次全量重扫请求。

        指纹本身只把「要不要扫」记进 _band_change_reason（由 observe_visible_desks
        在 ui_lock 之外消费），真正写快照的永远是重扫的权威读数。屏形状不同一律不比。
        """
        previous, geometry, signature = self._read_band_baseline(desk_wrappers)
        if signature is None or previous is None:
            return
        previous_geometry, previous_signature = previous
        if previous_geometry != geometry:
            return
        if previous_signature != signature:
            self._band_change_reason = (
                "Visible seat band changed while seat identity is unknown "
                "(no numeric seat label anchor); triggering full rescan."
            )

    def _read_visible_seats(
        self, desk_wrappers: list, *, band: Optional[str] = None
    ) -> Dict[int, Tuple[any, str, dict]]:
        """把可见桌位读成 {seat_number: (desk, side, info)}。

        座位号身份未知的桌位不会出现在结果里（见 _map_desks_with_identity），
        所以进入快照的读数都带着「座位号由锚点确定」这个前提。band 为已知滚动
        相位（展开重扫路径），锚点缺失时据此定座位号。

        逐桌原始读数（每侧 state/imgs/label/occupied 与丢弃原因）不再随结果返回：
        它只在 DEBUG 落盘，而重扫每轮产出两条、常驻成片刷屏，却从不参与任何判断。
        排障要看某号位为什么被读成空/占，在座次表之外直接查 page_source dump。
        """
        mapped, _dropped, _offset_source = self._map_desks_with_identity(desk_wrappers, band=band)

        observed: Dict[int, Tuple[any, str, dict]] = {}
        for desk_idx, desk, _self_anchored in mapped:
            for side, offset in (("left", 1), ("right", 2)):
                seat_num = desk_idx * 2 + offset
                observed[seat_num] = (desk, side, self._extract_seat_info(desk, side, seat_num))
        return observed

    async def _resolve_usernames(
        self,
        observed: Dict[int, Tuple[any, str, dict]],
        plan=None,
    ) -> None:
        """执行账本判定的身份补齐：沿用快照已知占位者，读不到再点头像弹窗。

        证据来路、一人一麦位、残留渲染与未知身份退避都在 `SeatLedger`；这里只负责
        挑出可交互的桌位、持有 UI 会话、执行 `inspect_occupant` 并回填结果。
        """
        plan = plan or self.ledger.prepare_identity_resolution(observed)

        # 裁剪残片桌位（高度不足以交互）在当前视口无法通过点头像读取昵称，绝不盲目点击
        pending = [
            (seat_num, desk, side)
            for seat_num, desk, side in plan.pending
            if self._is_desk_interactable(desk)
        ]
        if not pending:
            return

        if not self.panel_reader.can_probe_ui:
            self.logger.debug("UI 锁被外部任务持有，本轮座位名片探测跳过")
            return

        async def _inspect_pending():
            for seat_num, desk, side in pending:
                username = await self.inspect_occupant(desk, side, seat_num)
                self.ledger.apply_probe_result(plan, seat_num, username)

        if self.panel_reader.holds_session:
            await _inspect_pending()
        else:
            async with self.panel_reader.session("seat_inspect"):
                await _inspect_pending()

    async def _sync_desks(
        self,
        desk_wrappers: list,
        trigger_source: str,
        focus_count: Optional[int],
        *,
        notify_after: Optional[int] = None,
    ) -> Tuple[bool, Set[Tuple[int, str]]]:
        """映射 -> 读麦位 -> 补昵称 -> 分类 -> 落快照 -> diff -> 通知。

        返回 (快照是否有变更, 去向不明需要全量扫描的变更指纹)。

        被动观测与背离重扫共用这一段；区别只在触发源文案以及通知里的人数取值。
        """
        # 被动观测不滚面板、视口可能停在任何位置：座位号读不到就不写（见 _read_visible_seats）
        observed = self._read_visible_seats(desk_wrappers)
        if not observed:
            # 身份未知（读不出任何座位号）时整屏读数都被丢弃 —— 但这不等于「没有
            # 变化」。房间里只有群主/管理占座、或第二排只露出顶部（label 节点根本
            # 没 dump 进来）时就是这个情形，靠放大镜也读不出编号，只能拿可见带的
            # 内容指纹比对：指纹变了就升级为全量重扫（重扫相位已知，能对上座位号）。
            self._note_band_change(desk_wrappers)
            return False, set()

        # 身份可解析的轮次不需要指纹兜底，但基线必须照样刷新（按屏形状比对，
        # 见 _read_band_baseline）：清掉基线等于放弃下一轮的比对资格。
        self._read_band_baseline(desk_wrappers)

        change = self.ledger.observe(observed)
        await self._resolve_usernames(observed, change.plan)

        # 锁只罩 apply：observe → 弹窗 → apply 之间不能持锁，否则闸门锁与 UI
        # 会话会形成 AB-BA 死锁；apply 会按当前快照重新分类，并发落下的视口
        # 同步不会被这一轮的旧分类覆盖。
        async with self._lock:
            diff = self.ledger.apply(change)

        if diff.has_changes:
            self.logger.info(
                self.format_3row_layout(
                    trigger_source=trigger_source,
                    focus_count=focus_count,
                    changed_seats=diff.changed_seats,
                )
            )

            if diff.changed_users:
                from ushareiplay.managers.command_manager import CommandManager
                if notify_after is None:
                    # 被动观测没有新的人数，用最新在座数作为 after
                    notify_after = self.ledger.total_seated()
                await CommandManager.instance().notify_focus_count_change(
                    self._last_focus_count,
                    notify_after,
                    changed_users=diff.changed_users,
                    seat_info=diff.seat_info,
                )

        if focus_count is not None:
            self._last_focus_count = focus_count

        if diff.unexplained:
            self.logger.debug(f"[seat-obs] 变更去向不明 {sorted(diff.unexplained)}")

        return diff.has_changes, diff.unexplained

    async def observe_visible_desks(
        self, desk_wrappers: list, current_focus_count: Optional[int] = None
    ) -> bool:
        """被动观测当前可见的桌位，检测变动并维护全局快照。

        三类信号都会触发一次全量重扫（同一份信号只扫一次，见 _request_full_scan）：
        - 专注人数变化：有人进/出专注，看不看得见都一样；
        - 视口里出现「变更了但去向不明」的读数：有人消失、凭空出现、同一位子换人；
        - 座位号读不出来（没有数字 label 锚点）时可见带内容指纹变化：读数进不了
          快照，但变动确实发生了，交给相位已知的重扫去对上座位号。
        """
        if not desk_wrappers:
            return False

        has_changes, unexplained = await self._sync_desks(
            desk_wrappers,
            "可视区域变更",
            current_focus_count,
        )
        band_change_reason = self._band_change_reason
        self._band_change_reason = None

        target_focus = self._resolve_target_focus(current_focus_count)

        # 被动观测只看得到一部分麦位，「在座数 != 专注人数」本身不构成异常，
        # 按专注人数取值对账即可（同一人数只重扫一次）。
        scanned = await self._reconcile_focus_count(target_focus)
        if band_change_reason is not None and not scanned:
            await self._request_full_scan(target_focus=target_focus, reason=band_change_reason)
            if not self._last_rescan_ok:
                # 重扫没落地（展开按钮找不到/半截快照）时读数还是旧的：把信号留着，
                # 下一轮再试（重试间隔由 _request_full_scan 的冷却兜住）。否则这次
                # 变更就永久丢了 —— 真机上「换座后快照停在旧位子」就是这么来的。
                self._band_change_reason = band_change_reason
        await self._resolve_unexplained_changes(
            unexplained, target_focus, already_scanned=scanned
        )

        return has_changes

    def _resolve_target_focus(self, current_focus_count: Optional[int]) -> Optional[int]:
        """本轮观测对应的人数：优先用事件带过来的，其次最近已知的，最后问 RoomState。"""
        if current_focus_count is not None:
            return current_focus_count
        if self._last_focus_count is not None:
            return self._last_focus_count
        try:
            from ushareiplay.state.room_state import RoomState
            return RoomState.instance().focus_count
        except Exception:
            return None

    async def on_focus_count(self, before: Optional[int], current_focus_count: int) -> bool:
        """专注人数发生变化时调用。与在座人数背离时打破被动规则，主动展开全量扫描。"""
        self._last_focus_count = current_focus_count
        return await self._reconcile_focus_count(current_focus_count)

    async def _reconcile_focus_count(self, target_focus: Optional[int]) -> bool:
        """按专注人数对账：同一个取值最多触发一次全量重扫。"""
        should_scan, total_seated = self.ledger.begin_focus_reconciliation(target_focus)
        if not should_scan:
            return False

        attempted = await self._request_full_scan(
            target_focus=target_focus,
            reason=(
                f"Focus divergence detected: focus_count={target_focus}, known_seated={total_seated}. "
                "Triggering active expansion rescan."
            ),
        )
        if not attempted or not self._last_rescan_ok:
            # 被冷却挡下、或扫描没真正落地：撤掉登记，留给下一轮重试
            self.ledger.rollback_focus_reconciliation()
        return attempted and self._last_rescan_ok

    async def _resolve_unexplained_changes(
        self,
        unexplained: Set[Tuple[int, str]],
        target_focus: Optional[int],
        *,
        already_scanned: bool = False,
    ) -> bool:
        """视口里出现去向不明的变更 → 全量扫描一遍，取最最最新的座位信息。"""
        fingerprint = self.ledger.unexplained_scan_fingerprint(
            unexplained, already_scanned=already_scanned
        )
        if fingerprint is None:
            return False
        return await self._request_full_scan(
            target_focus=target_focus,
            fingerprint=fingerprint,
            reason=(
                f"Seat change with unknown destination {sorted(unexplained)}; "
                "triggering full rescan."
            ),
        )

    async def _request_full_scan(
        self,
        *,
        target_focus: Optional[int],
        reason: str,
        fingerprint: Optional[frozenset] = None,
    ) -> bool:
        """统一的展开重扫入口：冷却 + 指纹去重 + 失败回滚。

        返回 True 表示扫描确实执行过（成败看 _last_rescan_ok），False 表示被冷却或
        指纹挡下、根本没扫。闸门都是先登记再扫：重扫要十几秒，期间事件轮询会反复进来。
        """
        if not self.ledger.begin_rescan(fingerprint):
            return False
        self.logger.info(reason)
        await self.expand_rescan_and_collapse(target_focus)
        if not self._last_rescan_ok and fingerprint is not None:
            # 扫描没落地（展开失败/半截快照）：撤掉指纹，留给下一轮重试
            self.ledger.clear_scanned_fingerprint()
        # 返回值表示「扫描确实执行过」，成败一律看 _last_rescan_ok
        return True

    async def _scan_all_rows_expanded(self, initial_desks: list) -> Dict[int, Tuple[any, str, dict]]:
        """
        在展开状态下执行双向全量扫描：
        1. 滑到第一排（Row 0），观测前两排（1~8号座位）并解析未识别昵称；
        2. 滑到第三排（Row 2），观测后两排（5~12号座位）并解析未识别昵称；
        3. 合并两次观测结果，确保 1~12 号座位全部完整覆盖，最后滑回第一排复位。
        """
        observed_all: Dict[int, Tuple[any, str, dict]] = {}

        # 1. 滑动至第一排（Row 0），使第一排（1~4号）和第二排（5~8号）处于可视视口
        if hasattr(self.seat_ui, "scroll_to_row"):
            try:
                self.seat_ui.scroll_to_row(0, initial_desks, duration=300)
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.debug(f"Scroll to top row failed: {e}")

        top_desks = None
        if self.handler and hasattr(self.handler, "element_finder"):
            try:
                top_desks = self.handler.element_finder.find_elements("seat_desk")
            except Exception:
                pass
        if not top_desks:
            top_desks = initial_desks

        # 顶部相位：前两排（desk 0..3）在视口里。相位由本方法自己的滚动决定，
        # 滚动被内容顶部夹住 —— 带位一定从第一排起（无锚点也能定座位号）。
        top_observed = self._read_visible_seats(top_desks, band="top")
        await self._resolve_usernames(top_observed)
        observed_all.update(top_observed)

        # 2. 滑动至第三排（Row 2），使第二排（5~8号）和第三排（9~12号）处于可视视口
        if hasattr(self.seat_ui, "scroll_to_row"):
            try:
                self.seat_ui.scroll_to_row(4, top_desks, duration=300)
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.debug(f"Scroll to bottom row failed: {e}")

        bottom_desks = None
        if self.handler and hasattr(self.handler, "element_finder"):
            try:
                bottom_desks = self.handler.element_finder.find_elements("seat_desk")
            except Exception:
                pass
        if not bottom_desks:
            bottom_desks = top_desks

        # 底部相位：后两排（desk 2..5）在视口里。滚动被内容底部夹住 —— 带位一定到
        # 第三排止，可见桌位从末尾倒着数（无锚点也能定座位号）。
        bottom_observed = self._read_visible_seats(bottom_desks, band="bottom")
        # 同一轮里两个相位都读到的麦位（如 5~8 号）共享昵称，省掉重复弹窗检查。
        # 只共享本轮读数：旧快照里的占座者一律不往这里抄 —— 那是「沿用旧值」的活，
        # 由 _resolve_usernames 带着「一人不占两座」的约束去做（真机上的重复占座
        # 就是这里绕过约束、把已经换到 11 号的 Outlier 又钉回 9 号位）。
        for seat_num, item in bottom_observed.items():
            shared = top_observed.get(seat_num)
            if (
                item[2].get("occupied")
                and not item[2].get("username")
                and shared is not None
                and shared[2].get("username")
            ):
                shared_name = shared[2]["username"]
                if shared_name not in claimed_usernames(bottom_observed):
                    item[2]["username"] = shared_name
                    if not item[2].get("label") and shared[2].get("label"):
                        item[2]["label"] = shared[2]["label"]
                        item[2]["is_owner"] = shared[2].get("is_owner", False)

        await self._resolve_usernames(bottom_observed)

        for seat_num, item in bottom_observed.items():
            if seat_num not in observed_all:
                observed_all[seat_num] = item
            elif evidence_weight(item[2]) > evidence_weight(observed_all[seat_num][2]):
                # 两个相位读同一个位子，留回答力度大的那条。旧规则只认「新读数占座」
                # 和「新读数有昵称」两种升级：底相位明确读到「点击入座」的空座，盖不过
                # 顶相位那条什么都没读到的空读数，于是这个位子谁都不写 —— 快照里的旧
                # 占座者就此长驻（真机 23:00:0x 的 9 号位）。
                if not item[2].get("label") and observed_all[seat_num][2].get("label"):
                    item[2]["label"] = observed_all[seat_num][2]["label"]
                    item[2]["is_owner"] = observed_all[seat_num][2].get("is_owner", False)
                observed_all[seat_num] = item
            else:
                if not observed_all[seat_num][2].get("label") and item[2].get("label"):
                    observed_all[seat_num][2]["label"] = item[2]["label"]
                    observed_all[seat_num][2]["is_owner"] = item[2].get("is_owner", False)

        # 3. 滑回第一排（复位到默认可视区域）
        if hasattr(self.seat_ui, "scroll_to_row"):
            try:
                self.seat_ui.scroll_to_row(0, bottom_desks, duration=300)
                await asyncio.sleep(0.2)
            except Exception as e:
                self.logger.debug(f"Reset scroll to top failed: {e}")

        return observed_all

    def _desks_on_screen(self) -> list:
        """当前页面里的桌位（展开按钮不可用时的降级来源，只读不点）。"""
        finder = getattr(self.handler, "element_finder", None)
        if finder is None or not hasattr(finder, "find_elements"):
            return []
        try:
            return list(finder.find_elements("seat_desk") or [])
        except Exception:
            return []

    async def expand_rescan_and_collapse(self, target_focus_count: int) -> bool:
        """
        主动展开面板 -> 全量双向重扫 12 个座位（滑到顶扫前两排，滑到底扫后两排） -> 复位并收起。
        """
        if not self.handler:
            return False

        # 记为「没落地」：中途失败/半截快照时调用方要据此保留闸门、下轮重试
        self._last_rescan_ok = False
        # 这一扫就是那次补扫本身：先撤销欠账，结不结由 _verify_focus_consistency 说
        self._consistency_retry_due = False

        async with self._ui_session("seat_expansion"):
            try:
                # 人数是「这遍扫对没有」的唯一判据，而调用方带进来的值在冷启动/
                # RoomState.clear() 之后是 None。这里已在 ui_session 内，可以安全地
                # 按需补读一次界面 —— 读不到才继续用 None（保持「未知」而不是猜）。
                if target_focus_count is None:
                    target_focus_count = self.read_focus_count_from_ui()

                # 用规范 helper：展开失败或桌位不足 6 张都返回 None，避免半截快照
                seat_desks = await self.seat_ui.expand_and_find_desks()
                if not seat_desks:
                    # 展开按钮找不到（弹窗/动画切换中）或面板本来就展开着时直接放弃，
                    # 会把这次变更整轮丢掉（真机日志：Failed to expand seats for full rescan）。
                    # 退回当前页面里的桌位继续扫，可信范围由带几何校验的相位映射裁决：
                    # 相位不成立的部分一律丢弃，不会写错座位号。
                    seat_desks = self._desks_on_screen()
                    if not seat_desks:
                        self.logger.warning("Failed to expand seats for full rescan")
                        return False
                    self.logger.warning(
                        f"Seat expansion unavailable; rescanning {len(seat_desks)} on-screen desks"
                    )

                # 双向扫描覆盖全部 3 排座位（顶部前两排与底部后两排）
                observed = await self._scan_all_rows_expanded(seat_desks)
                if not observed:
                    return False

                async with self._lock:
                    # 权威路径：两个相位把 12 个座位都读过，明确空座即可判下座
                    change = self.ledger.observe(
                        observed, resolve_identity=False, authoritative=True
                    )
                    diff = self.ledger.apply(change)
                    self._last_rescan_ok = True

                # 重扫是十几秒的主动行为，落地就得给出结论：没有变更也打印，否则没人
                # 能判断这次到底读到了什么（真机 23:00:0x：扫完一个字节都没输出，
                # 「1 个专注」到底坐在哪无从核对）。
                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="专注人数背离展开重扫",
                        focus_count=target_focus_count,
                        changed_seats=diff.changed_seats,
                    )
                )

                if diff.changed_users:
                    from ushareiplay.managers.command_manager import CommandManager
                    await CommandManager.instance().notify_focus_count_change(
                        self._last_focus_count,
                        target_focus_count,
                        changed_users=diff.changed_users,
                        seat_info=diff.seat_info,
                    )

                if target_focus_count is not None:
                    self._last_focus_count = target_focus_count

                # 重扫的结论必须跟房间唯一的硬数字自洽，否则这次账没对上
                self.ledger.verify_focus_consistency(observed, target_focus_count)

                return diff.has_changes

            except Exception:
                self.logger.error(f"Error during expand_rescan_and_collapse: {traceback.format_exc()}")
                return False
            finally:
                try:
                    await self.seat_ui.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats after rescan: {e}")


    async def sync_current_viewport(
        self, band: Optional[str] = None, page_source: Optional[str] = None
    ) -> Dict[int, Tuple[any, str, dict]]:
        """从 driver.page_source 提取可见桌位，按滚动相位映射并同步 DOM 证据至快照。

        Args:
            band: 已知滚动相位（"top" / "bottom"）。
            page_source: 可选页面 XML 字符串；若为 None 则从 driver.page_source 获取。

        Returns:
            observed: {seat_number: (desk, side, info)}，本轮视口中识别出的麦位及读数。
        """
        if page_source is None:
            driver = getattr(self.handler, "driver", None)
            if driver and hasattr(driver, "page_source"):
                page_source = driver.page_source

        if not page_source:
            return {}

        try:
            root = etree.fromstring(page_source.encode("utf-8"))
        except Exception as e:
            self.logger.warning(f"Failed to parse page_source XML for viewport sync: {e}")
            return {}

        locator = self._element_locator("seat_desk")
        if locator is None:
            return {}
        nodes = root.xpath(locator.absolute_xpath)

        desk_wrappers = [ElementWrapper(node, self.handler, "seat_desk") for node in nodes]
        if not desk_wrappers:
            return {}

        async with self._lock:
            observed = self._read_visible_seats(desk_wrappers, band=band)
            if not observed:
                return {}

            # 沿用快照中已知的昵称
            for seat_num, (desk, side, info) in observed.items():
                if info["occupied"] and not info.get("username"):
                    old_slot = self.seats.get(seat_num)
                    if old_slot and old_slot.occupied and old_slot.username:
                        info["username"] = old_slot.username

            # 视口可见麦位具有直接 DOM 证据，明确空座允许清空旧快照
            diff = self.ledger.apply_viewport(observed)

            if diff.has_changes:
                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="视口同步",
                        focus_count=self._last_focus_count,
                        changed_seats=diff.changed_seats,
                    )
                )

            return observed

    def mark_owner_seated(self, seat_number: int, username: Optional[str] = None) -> None:
        """确认就座后立即写入快照、更新基准并标记已对账。

        换座不是新增：房主原本就有位子时（真机 09-28 18:07:08，:seat 2 11 是
        10→11 的移动），必须先腾出旧位子，且专注人数不变 —— 房间里的硬数字只认
        人头，不认位移。旧实现无条件 +1 且不清旧位：同一个人占两座、RoomState
        凭空 1→2，下一轮被动观测拿真实读数（1）一比就判成背离，引爆整轮全量重扫。
        """
        owner_username = username or self._owner_nickname() or "群主"

        delta = self.ledger.mark_owner_seated(seat_number, owner_username)

        current = self._last_focus_count
        if current is None:
            try:
                from ushareiplay.state.room_state import RoomState
                current = RoomState.instance().focus_count
            except Exception as e:
                self.logger.debug(f"RoomState focus_count unavailable, falling back to seated count: {e}")
                current = None

        if current is not None:
            # 换座/原地重记的人头已经在专注人数里，只有真正新增一个在座者才 +1
            new_count = current + delta
        else:
            new_count = self.ledger.total_seated()

        self._last_focus_count = new_count
        self._reconciled_focus_count = new_count

        try:
            from ushareiplay.state.room_state import RoomState
            RoomState.instance().focus_count = new_count
        except Exception as e:
            # 对账闸门读的是 _reconciled_focus_count 与快照座位数，不读 RoomState，
            # 所以这里写失败不会误触发重扫；但 RoomState 会停在旧值，必须留痕。
            self.logger.warning(f"Failed to write RoomState.focus_count={new_count} after seating: {e}")

