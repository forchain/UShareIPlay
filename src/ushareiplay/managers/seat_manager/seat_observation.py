from __future__ import annotations

import asyncio
import logging
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Dict, List, Optional, Set, Tuple

from lxml import etree

from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.core.singleton import Singleton


@dataclass(frozen=True)
class SeatRescanCooldownPolicy:
    """重扫冷却策略值对象，集中管理各类重扫/补扫的退避时长与时间流逝判定。"""

    rescan_cooldown: float = 3.0
    rescan_retry_cooldown: float = 30.0
    consistency_rescan_cooldown: float = 10.0
    residual_inspect_cooldown: float = 60.0
    time_fn: Callable[[], float] = time.monotonic

    def is_residual_inspect_cooldown_expired(self, last_inspect_time: float) -> bool:
        return (self.now() - last_inspect_time) >= self.residual_inspect_cooldown

    def get_cooldown(self, *, last_rescan_ok: bool, consistency_retry_due: bool) -> float:
        cooldown = self.rescan_cooldown if last_rescan_ok else self.rescan_retry_cooldown
        if consistency_retry_due:
            cooldown = max(cooldown, self.consistency_rescan_cooldown)
        return cooldown

    def is_cooldown_expired(
        self,
        last_rescan_time: float,
        *,
        last_rescan_ok: bool,
        consistency_retry_due: bool,
    ) -> bool:
        cooldown = self.get_cooldown(
            last_rescan_ok=last_rescan_ok,
            consistency_retry_due=consistency_retry_due,
        )
        return (self.now() - last_rescan_time) >= cooldown

    def now(self) -> float:
        return self.time_fn()


@dataclass
class SeatObservationGateState:
    """Seat Observation 决策与协调闸门状态，支持单动作整体重置。

    包含 11 个协调字段：
    - last_focus_count: 最近一次视口/外部同步的专注人数
    - reconciled_focus_count: 最近一次已完成对账的专注人数（防展开收起死循环）
    - scanned_seat_change_fingerprint: 最近一次「去向不明」变更的读数指纹
    - last_rescan_ok: 最近一次全量重扫是否真正落地
    - last_rescan_time: 最近一次重扫执行时刻
    - last_visible_band: 身份未知时可见麦位带基线 (几何形状, 内容指纹)
    - band_change_reason: 带变化原因
    - residual_seats: 已确认的残留渲染 {位子: 人}
    - last_scan_fingerprint: 最近一次全量确定的重扫读数指纹
    - consistency_retry_due: 是否欠一次补扫
    - lock: 麦位状态互斥锁
    """

    last_focus_count: Optional[int] = None
    reconciled_focus_count: Optional[int] = None
    scanned_seat_change_fingerprint: Optional[frozenset] = None
    last_rescan_ok: bool = False
    last_rescan_time: float = 0.0
    last_visible_band: Optional[Tuple] = None
    band_change_reason: Optional[str] = None
    residual_seats: Dict[int, str] = field(default_factory=dict)
    residual_seats_inspected_at: Dict[int, float] = field(default_factory=dict)
    last_scan_fingerprint: Optional[frozenset] = None
    consistency_retry_due: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def reset(self) -> None:
        """单动作整体重置所有协调与决策闸门状态回初始默认值。"""
        fresh = SeatObservationGateState()
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(fresh, f))

    def __getattr__(self, name: str):
        if name.startswith("_") and name[1:] in self.__dataclass_fields__:
            return getattr(self, name[1:])
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value):
        if name.startswith("_") and name != "_gate_state" and name[1:] in self.__dataclass_fields__:
            super().__setattr__(name[1:], value)
        else:
            super().__setattr__(name, value)


@dataclass
class SeatSlot:
    seat_number: int  # 1..12
    occupied: bool = False
    username: Optional[str] = None
    label: str = ""
    is_owner: bool = False

    def copy(self) -> "SeatSlot":
        return SeatSlot(
            seat_number=self.seat_number,
            occupied=self.occupied,
            username=self.username,
            label=self.label,
            is_owner=self.is_owner,
        )


class SeatObservationManager(Singleton):
    """
    负责麦位被动观测、全量 12 麦位状态维护、3 排视觉快照日志输出、
    以及专注人数与可视麦位背离时的自动展开探测。
    """

    DEFAULT_COOLDOWN_POLICY: ClassVar[SeatRescanCooldownPolicy] = SeatRescanCooldownPolicy()
    RESCAN_COOLDOWN: ClassVar[float] = DEFAULT_COOLDOWN_POLICY.rescan_cooldown
    # 上一次重扫没落地（展开失败/半截快照）时的重试间隔：放宽到几十秒，
    # 既不会把信号吞掉，也不会让失败的展开每几秒刷一次日志。
    RESCAN_RETRY_COOLDOWN: ClassVar[float] = DEFAULT_COOLDOWN_POLICY.rescan_retry_cooldown
    # 重扫落地了、但结论与专注人数不自洽时的补扫间隔：展开收起会逼面板重绘，
    # 残留 label 通常在第二遍就清掉，但一次展开要十几秒，不能按 3 秒追着扫。
    CONSISTENCY_RESCAN_COOLDOWN: ClassVar[float] = DEFAULT_COOLDOWN_POLICY.consistency_rescan_cooldown

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
    ):
        self.handler = handler
        self._logger = None
        self._controller = None
        self._seat_ui = seat_ui
        self.cooldown_policy = cooldown_policy or self.DEFAULT_COOLDOWN_POLICY
        self.gate_state = gate_state or SeatObservationGateState()
        # 全局 1~12 号位快照
        self.seats: Dict[int, SeatSlot] = {
            i: SeatSlot(seat_number=i) for i in range(1, 13)
        }

    @property
    def _gate_state(self) -> SeatObservationGateState:
        return self.gate_state

    @_gate_state.setter
    def _gate_state(self, val: SeatObservationGateState):
        self.gate_state = val

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
            if self._seat_ui:
                self._seat_ui.handler = handler
            if hasattr(self.handler, "logger") and self.handler.logger:
                self._logger = self.handler.logger
            if hasattr(self.handler, "controller") and self.handler.controller:
                self._controller = self.handler.controller
        return self

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
        if self._seat_ui is None:
            from ushareiplay.managers.seat_manager.seat_ui import SeatUIManager
            if SeatUIManager.is_initialized():
                self._seat_ui = SeatUIManager.instance()
        return self._seat_ui

    def clear(self):
        """重置所有麦位状态与决策闸门状态"""
        self.seats = {i: SeatSlot(seat_number=i) for i in range(1, 13)}
        self.gate_state.reset()
        self.logger.info("Cleared seat observation snapshot")

    @asynccontextmanager
    async def _ui_session(self, reason: str):
        """独占 UI 执行权，契约与 AppController.ui_session 一致。

        EventManager 的兜底 press_back 只看 AppController.ui_lock 是否被持有
        （见 runtime_context.is_ui_busy），所以点头像读昵称、展开/收起座位面板
        都必须走真实的 ui_session；否则命令任务与自动 back 会把资料弹窗当成
        未知页面处理，读到的昵称随之丢失。

        controller 缺席（单元测试）时退化为不加锁；controller 在场但接口不符
        契约时直接抛错，而不是静默裸奔。
        """
        ctrl = self.controller
        if ctrl is None:
            yield
            return
        async with ctrl.ui_session(reason):
            yield

    def _element_selector(self, element_key: str) -> Optional[str]:
        """从 config.yaml 里取元素选择器。

        生产上 handler.config 是 soul 段（AppController 用 self.config["soul"]
        构造 SoulHandler），所以 elements 通常在顶层；兼容传根的 config，与
        ElementFinder._get_locator / EventManager._screen_elements 的取法一致。
        """
        config = getattr(self.handler, "config", None)
        if isinstance(config, dict):
            elements = config.get("elements")
            if not isinstance(elements, dict):
                soul = config.get("soul")
                elements = soul.get("elements") if isinstance(soul, dict) else None

            selector = elements.get(element_key) if isinstance(elements, dict) else None
            if isinstance(selector, str) and selector.strip():
                return selector.strip()

        _FALLBACK_SELECTORS = {
            "seat_desk": "cn.soulapp.android:id/userRoot",
            "left_seat": "cn.soulapp.android:id/leftUserView",
            "right_seat": "cn.soulapp.android:id/rightUserView",
            "left_state": "cn.soulapp.android:id/leftClState",
            "right_state": "cn.soulapp.android:id/rightClState",
            "left_label": "cn.soulapp.android:id/leftTvLabelH",
            "right_label": "cn.soulapp.android:id/rightTvLabelH",
            "left_default_name": "cn.soulapp.android:id/leftTvDefaultName",
            "right_default_name": "cn.soulapp.android:id/rightTvDefaultName",
            "left_avatar": "cn.soulapp.android:id/leftAvatarView",
            "right_avatar": "cn.soulapp.android:id/rightAvatarView",
            "left_rank": "cn.soulapp.android:id/leftRankView",
            "right_rank": "cn.soulapp.android:id/rightRankView",
            "empty_seat": "cn.soulapp.android:id/leftTvDefaultName",
        }
        return _FALLBACK_SELECTORS.get(element_key)

    def _find_child_element(self, desk, element_key: str):
        """按 config.yaml 的元素 key 在 desk 下查找子元素。

        desk 在生产里有两种形状，必须都按 *元素 key* 解析选择器：
        - 事件轮询给的 ElementWrapper：只有 lxml 快照，在本节点内按相对 XPath 查；
        - 展开重扫时 element_finder.find_elements 给的 raw WebElement。
        元素 key（如 left_state）是 resource-id 而不是 XPath，直接丢给
        ElementWrapper.find_child_element 会静默返回 None。
        """
        if desk is None:
            return None

        selector = self._element_selector(element_key)
        if selector is None:
            self.logger.debug(f"No configured selector for seat element '{element_key}'")
            return None

        if isinstance(desk, ElementWrapper):
            if selector.startswith("//") or selector.startswith("."):
                xpath = selector if selector.startswith(".") else f".{selector}"
            else:
                xpath = f".//*[@resource-id='{selector}']"
            try:
                return desk.find_child_element(xpath)
            except Exception:
                return None

        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return None
        return finder.find_child_element(desk, element_key, log_failure=False)

    def _avatar_image_count(self, desk, side: str) -> int:
        """AvatarView 里的 ImageView 数量（空座恰好一张占位图，占座是头像+挂件）。

        只对快照（ElementWrapper）数图：它在本地 lxml 上按子树查，是真正收敛到
        AvatarView 里的。展开重扫拿到的是 raw WebElement，而 Appium 的 XPath 是
        整页作用域（不随父元素收敛），照数会数到全屏的图，把每个麦位都读成占座 ——
        所以那条路径返回 0（没读到），占用/空座由同在 DOM 里的 ClState、昵称、
        麦位编号判定（见 #341）。

        Appium 在真实 Android 页面转储中通常使用框架类名作为 XML 标签名
        （如 <android.widget.ImageView>），且往往不附带 class="..." 属性；
        而在部分测试或快照中可能为 <node class="...">。因此同时匹配标签名与 class 属性。
        """
        avatar = self._find_child_element(desk, f"{side}_avatar")
        if not isinstance(avatar, ElementWrapper):
            return 0
        xpath = (
            f".//*[self::{self.IMAGE_VIEW_CLASS} or self::ImageView "
            f"or @class='{self.IMAGE_VIEW_CLASS}' or @class='ImageView']"
        )
        return len(avatar.find_child_elements(xpath))

    def _read_seat_dom(self, desk, side: str) -> dict:
        """一侧麦位的原始 DOM 证据：只读数，不判定空/占。"""
        return {
            "label": self._get_label_text(desk, side),
            "avatar_images": self._avatar_image_count(desk, side),
            "has_state": self._find_child_element(desk, f"{side}_state") is not None,
            "has_default": self._find_child_element(desk, f"{side}_default_name") is not None,
            "has_rank": self._find_child_element(desk, f"{side}_rank") is not None,
        }

    @staticmethod
    def _is_seat_number_label(label: str) -> bool:
        """label 是房间给空座标的麦位编号（1~12 纯数字）。"""
        return label.isdigit() and 1 <= int(label) <= 12

    def _has_occupancy_evidence(self, dom: dict) -> bool:
        """占座证据（纯 DOM，见 #341）：

        - AvatarView 里多于一张图（头像 + 挂件/边框）；
        - ClState 存在 —— 空座渲染 TvDefaultName 或纯数字编号、不带 ClState，
          这与 seating.py 定座流程沿用的判据（bool(left_state)）是同一个，
          ClState 里的勋章 / 专注时长等活跃控件据此天然覆盖；
        - RankView（勋章/段位图标）存在 —— 房间里只有在座用户才会渲染段位图标；
        - label 是非空的昵称/角色文本（既不是麦位编号，也不是「点击入座」）。

        正向证据优先：只要有一条成立就算占座，绝不因为另一条空座证据把它推平。
        """
        label = dom["label"].strip()
        if dom["avatar_images"] > 1:
            return True
        if dom["has_state"]:
            return True
        if dom.get("has_rank"):
            return True
        return (
            bool(label)
            and not self._is_seat_number_label(label)
            and label not in self.EMPTY_SEAT_LABELS
        )

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
                if not is_admin and (slot.label == "管理" or self._is_known_room_admin(slot.username)):
                    is_admin = True
                    if slot.username:
                        self._record_room_admin(slot.username)


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
        """查询用户当前所占麦位号（1..12），若不在麦上则返回 None。"""
        if not username:
            return None
        for num, slot in self.seats.items():
            if slot.occupied and slot.username == username:
                return num
        return None

    def get_all_seated_users(self) -> Dict[str, int]:
        """返回当前所有在座用户及其麦位号映射 {username: seat_number}。"""
        seated = {}
        for num, slot in self.seats.items():
            if slot.occupied and slot.username:
                seated[slot.username] = num
        return seated

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

    def _get_label_text(self, desk, side: str) -> str:
        elem = self._find_child_element(desk, f"{side}_label")
        if elem and hasattr(elem, "text"):
            return elem.text or ""
        return ""

    def _judge_empty(self, dom: dict, seat_num: Optional[int] = None) -> bool:
        """明确的空座证据（纯 DOM，见 #341），与「看不见」严格区分：

        - TvDefaultName（点击入座）存在；
        - label 是 1~12 的麦位编号（房间里只有空位显示编号）；
        - AvatarView 里恰好一张占位图。

        滑出视口或折叠时 page source 只剩底座/空容器，一条都不成立 —— 那是「看不见」，
        不是「空座」，调用方不得据此推平快照。
        """
        if self._has_occupancy_evidence(dom):
            return False

        if dom["has_default"]:
            return True

        label = dom["label"].strip()
        if label in self.EMPTY_SEAT_LABELS:
            return True
        if self._is_seat_number_label(label):
            # 座位号已知时必须对得上：右侧读到 8 号不会把左侧 7 号位判空
            return seat_num is None or int(label) == seat_num
        return dom["avatar_images"] == 1

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
            if not isinstance(cfg, dict):
                return None
            return RolePolicy(cfg).configured_room_owner or None
        except Exception:
            return None

    def _is_known_room_admin(self, username: Optional[str]) -> bool:
        """检查用户是否为已知房间管理员（通过 AdminManager 或现有麦位记录）。"""
        if not username or username == "管理":
            return False
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            if AdminManager.is_initialized() and AdminManager.instance().is_room_admin(username):
                return True
        except Exception:
            pass
        if any(s.occupied and s.username == username and s.label == "管理" for s in self.seats.values()):
            self._record_room_admin(username)
            return True
        return False

    def _record_room_admin(self, username: Optional[str]) -> None:
        """记录用户为房间管理员（同步至 AdminManager）。"""
        if not username or username == "管理":
            return
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            if AdminManager.is_initialized():
                AdminManager.instance().add_room_admin(username)
        except Exception:
            pass

    def _is_known_owner(self, username: Optional[str]) -> bool:
        """检查用户是否为已知群主/房主。"""
        if not username or username == "群主":
            return False
        owner_name = self._owner_nickname()
        if owner_name and username == owner_name:
            return True
        return any(
            s.occupied and s.username == username and (s.is_owner or s.label == "群主")
            for s in self.seats.values()
        )

    def _apply_seat_role(self, slot: SeatSlot, info: dict, username: Optional[str]) -> None:
        """应用麦位角色（群主/管理/普通）并维护角色状态的一致性与持久性。"""
        new_label = info.get("label", "")
        new_is_owner = info.get("is_owner", False)

        if new_label == "管理":
            slot.label = "管理"
            slot.is_owner = False
            self._record_room_admin(username)
        elif new_is_owner or new_label == "群主":
            slot.is_owner = True
            slot.label = "群主"
        elif new_label and not self._is_seat_number_label(new_label):
            slot.label = new_label
            slot.is_owner = False
        else:
            # new_label 为空（视口被折叠/截断或 label 节点未 dump）或纯数字编号占位
            if self._is_known_owner(username) or (slot.username == username and slot.is_owner):
                slot.is_owner = True
                slot.label = "群主"
            elif self._is_known_room_admin(username) or (slot.username == username and slot.label == "管理"):
                slot.label = "管理"
                slot.is_owner = False
                self._record_room_admin(username)
            elif slot.username == username and slot.occupied and slot.label:
                # 同一用户在同一麦位，新读数无 label，保留旧 label 与身份
                pass
            else:
                slot.label = ""
                slot.is_owner = False

        info["label"] = slot.label
        info["is_owner"] = slot.is_owner


    def _extract_seat_info(self, desk, side: str, seat_num: Optional[int] = None) -> dict:
        dom = self._read_seat_dom(desk, side)
        label = dom["label"]
        occupied = self._has_occupancy_evidence(dom)

        is_owner = (label == "群主")
        username = None
        if is_owner:
            username = self._owner_nickname() or "群主"
        # 这里问的是「label 能不能当昵称用」，与 _has_occupancy_evidence 问的
        # 「label 是不是占座证据」是两个问题：管理/已占用是占座证据但不是昵称。
        elif label and not label.isdigit() and label not in ("管理", "已占用", "点击入座"):
            username = label

        is_empty = False
        if not occupied:
            is_empty = self._judge_empty(dom, seat_num)

        # has_state / has_default / avatar_images 只做诊断记录（判定空/占的原始依据），
        # 判据本身只看 _has_occupancy_evidence / _judge_empty。
        return {
            "occupied": occupied,
            "is_empty": is_empty,
            "label": label,
            "is_owner": is_owner,
            "username": username,
            "has_state": dom["has_state"],
            "has_default": dom["has_default"],
            "has_rank": dom.get("has_rank", False),
            "avatar_images": dom["avatar_images"],
        }

    def _desk_bounds(self, desk) -> Optional[dict]:
        """desk 的屏幕坐标（ElementWrapper 给 bounds，raw WebElement 给 location/size）。"""
        bounds = getattr(desk, "bounds", None)
        if isinstance(bounds, dict):
            return bounds
        location = getattr(desk, "location", None)
        size = getattr(desk, "size", None)
        if isinstance(location, dict) and isinstance(size, dict):
            return {
                "x": location.get("x", 0),
                "y": location.get("y", 0),
                "width": size.get("width", 0),
                "height": size.get("height", 0),
            }
        return None

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
            dom = self._read_seat_dom(desk, side)
            if self._has_occupancy_evidence(dom):
                return True
            if dom["label"].strip():
                return True
            if self._judge_empty(dom):
                return True
        return False

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
        if target_element is not None and not isinstance(target_element, ElementWrapper):
            try:
                target_element.click()
                return True
            except Exception:
                pass

        bounds = self._desk_bounds(desk)
        if not bounds or not bounds.get("width") or not bounds.get("height"):
            return False
        w, h = bounds["width"], bounds["height"]
        x = bounds["x"] + (w // 4 if side == "left" else (3 * w) // 4)
        y = bounds["y"] + h // 2

        gesture = getattr(self.handler, "gesture_handler", None)
        if gesture is None or not hasattr(gesture, "click_at"):
            return False
        return bool(gesture.click_at(x, y))

    # 麦位头像弹窗开着的证据：弹窗自己渲染的昵称节点（两种名片各一套 id）。
    # 与 RoomInfoWindow.DIALOG_KEYS 同一套判法：节点在 dump 里才说明弹窗开着。
    SEAT_CARD_EVIDENCE_KEYS = ("souler_name", "user_name")

    def _seat_card_still_present(self) -> bool:
        """头像名片此刻是否还在屏幕上 —— 关它的那次 back 只能由这个证据授权。

        反过来说：拿不到证据就绝不按 back。房间界面上的一次盲按 back 就是退出
        派对房间（RoomInfoWindow.ensure_closed 记过同一笔账）。
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
        房间（见 RoomInfoWindow.ensure_closed 的同款告诫），所以 back 必须由证据授权：
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

    @staticmethod
    def _seat_differs(old: SeatSlot, new: SeatSlot) -> bool:
        """同一个号位两次快照之间是否真的变了（占座与否 / 是谁 / label）。"""
        return (
            old.occupied != new.occupied
            or old.username != new.username
            or old.label != new.label
        )

    def _changed_seat_numbers(
        self,
        old_slots: Dict[int, SeatSlot],
        new_slots: Dict[int, SeatSlot],
        observed_seat_numbers: Set[int],
    ) -> Set[int]:
        """本轮落快照后确实变了的号位（座次表着色用）。"""
        return {
            num
            for num in observed_seat_numbers
            if old_slots.get(num) and new_slots.get(num)
            and self._seat_differs(old_slots[num], new_slots[num])
        }

    def _compute_diff(
        self,
        old_slots: Dict[int, SeatSlot],
        new_slots: Dict[int, SeatSlot],
        observed_seat_numbers: Set[int],
    ) -> Tuple[bool, List[str], Dict[str, dict]]:
        """比对观测到的麦位，产出变更用户与 seat_info（{action} 宏的来源）。

        {action} 取值：sit_down / leave_seat / move_seat。同一次观测里既离开
        旧位又坐到新位的用户合并为一条 move_seat（seat_number 为新位）。
        """
        changed_users = []
        seat_info = {}
        has_changes = False
        left_users: Set[str] = set()
        sat_seats: Dict[str, int] = {}

        for num in observed_seat_numbers:
            old = old_slots.get(num)
            new = new_slots.get(num)
            if not old or not new:
                continue

            if self._seat_differs(old, new):
                has_changes = True

            # 检测用户上座
            if not old.occupied and new.occupied and new.username:
                if new.username not in changed_users:
                    changed_users.append(new.username)
                sat_seats[new.username] = num
                seat_info[new.username] = {
                    "seat_number": num,
                    "action": "sit_down",
                }
            # 检测用户离座
            elif old.occupied and not new.occupied and old.username:
                if old.username not in changed_users:
                    changed_users.append(old.username)
                left_users.add(old.username)
                seat_info[old.username] = {
                    "seat_number": num,
                    "action": "leave_seat",
                }
            # 检测换人
            elif old.occupied and new.occupied and old.username and new.username and old.username != new.username:
                if old.username not in changed_users:
                    changed_users.append(old.username)
                seat_info[old.username] = {"seat_number": num, "action": "leave_seat"}

                if new.username not in changed_users:
                    changed_users.append(new.username)
                seat_info[new.username] = {"seat_number": num, "action": "sit_down"}

        # 同一次观测里离开又落座 = 换座位，合并成一条 move_seat
        for username in left_users:
            new_seat = sat_seats.get(username)
            if new_seat is not None:
                seat_info[username] = {"seat_number": new_seat, "action": "move_seat"}

        return has_changes, changed_users, seat_info

    def _plan_observation_changes(
        self,
        old_slots: Dict[int, SeatSlot],
        observed: Dict[int, Tuple[any, str, dict]],
    ) -> Tuple[Set[int], Set[int], Set[Tuple[int, str]]]:
        """把本轮视口读数与快照比对，分成「可以落快照」「视口内换座的旧位」「去向不明」。

        被动观测只看得到一部分麦位，因此只接受两类**完备**的变更：
        - 同一位子上还是同一个人（含昵称补齐）；
        - 视口内的换座：离座的人在同一轮观测的另一个位子上出现（去向可查）。

        其余任何变更都说明影响可能落在看不见的麦位上 —— 既不能凭一个局部读数写快照
        （会推出错误的座位信息），也不能当作没发生（那是漏检）：必须全量扫描一遍取
        最新信息。四种"去向不明"的情形都会进 fingerprint：
        disappear（有人从这个位子消失，去哪不知道）、appear（有人凭空出现在这个位子，
        或者这个人还在快照别处占着座）、swap（同一个位子换人，两边来去都不知道）、
        contested（本轮弹窗把快照挂在这个位子的人指到了别处，这里的身份已无证据）。
        """
        writable: Set[int] = set()
        clearable: Set[int] = set()
        unexplained: Set[Tuple[int, str]] = set()
        appears: Dict[int, Optional[str]] = {}
        disappears: Dict[int, Optional[str]] = {}

        for seat_num, (_desk, _side, info) in observed.items():
            old = old_slots.get(seat_num)
            if old is None:
                continue
            if info.get("identity_contested"):
                # 写「还坐着」等于替残留渲染背书（可视范围内换座就是被这样吞掉的），
                # 写「空了」又是拿局部读数猜去向 —— 一律不写，交给全量重扫。
                unexplained.add((seat_num, "contested"))
                continue
            if info["occupied"]:
                new_user = info.get("username")
                if not old.occupied:
                    appears[seat_num] = new_user
                elif old.username and new_user and old.username != new_user:
                    unexplained.add((seat_num, "swap"))
                else:
                    writable.add(seat_num)
            elif info.get("is_empty") and old.occupied:
                disappears[seat_num] = old.username
            # 读不到内容（不可见/渲染缺失）不算变更，保持快照原值

        for seat_num, user in disappears.items():
            matched = None
            if user:
                matched = next((s for s, u in appears.items() if u == user), None)
            if matched is None:
                unexplained.add((seat_num, "disappear"))
            else:
                # 视口内换座：去向已确定，旧位清空 + 新位占座都可以直接落快照
                writable.add(seat_num)
                writable.add(matched)
                clearable.add(seat_num)
                appears.pop(matched)

        for seat_num, user in appears.items():
            stale_seat = bool(user) and any(
                slot.occupied and slot.username == user
                for num, slot in old_slots.items()
                if num != seat_num
            )
            if user is None or stale_seat:
                # 昵称读不出来，或这个人还挂在快照的其它位子上（可能刚从看不见的位子挪过来）
                unexplained.add((seat_num, "appear"))
            else:
                writable.add(seat_num)

        return writable, clearable, unexplained

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
                dom = self._read_seat_dom(desk, side)
                sides.append(
                    (
                        dom["label"].strip(),
                        int(dom["avatar_images"]),
                        bool(dom["has_state"]),
                        bool(dom["has_default"]),
                        bool(dom.get("has_rank")),
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

    @staticmethod
    def _claimed_usernames(observed: Dict[int, Tuple[any, str, dict]]) -> Set[str]:
        """本轮读数里已经确定归属的昵称（label 直接读到昵称的那些麦位）。"""
        return {
            info["username"]
            for (_desk, _side, info) in observed.values()
            if info.get("occupied") and info.get("username")
        }

    def _placed_elsewhere(
        self, username: str, seat_num: int, observed: Dict[int, Tuple[any, str, dict]]
    ) -> bool:
        """本轮读数或快照里，这个人是不是在**别的**位子上有位置。"""
        # 1. 优先看本轮视口内其它麦位（最新读数）
        for other, (_desk, _side, info) in observed.items():
            if other != seat_num and info.get("occupied") and info.get("username") == username:
                return True
        # 2. 视口外的麦位看当前快照
        for other, slot in self.seats.items():
            if other != seat_num and other not in observed and slot.occupied and slot.username == username:
                return True
        return False

    def _mark_residual_seat(self, seat_num: int, info: dict, username: str) -> None:
        """把一个位子判成换座后的残留渲染：本轮读数的"占座"是像素，不是人。"""
        info["occupied"] = False
        info["is_empty"] = True
        info["username"] = None
        info["label"] = ""
        info["is_owner"] = False
        self._residual_seats[seat_num] = username

    def _prune_residual_records(
        self, observed: Dict[int, Tuple[any, str, dict]]
    ) -> Dict[int, str]:
        """清掉已经不成立的残留渲染记录，返回本轮仍然在场的：{位子: 人}。

        位子这一轮读不出占座（面板重绘了）或 label 直接读到别人（真有人新落座）时，
        记录当场作废。不在当前视口内的位子若该用户在快照中已不在任何麦位上也作废。
        """
        for seat_num in list(self._residual_seats):
            username = self._residual_seats[seat_num]
            item = observed.get(seat_num)
            if item is not None:
                info = item[2]
                if not info["occupied"]:
                    # 视口内明确读出非占座（面板已重绘），残留作废
                    del self._residual_seats[seat_num]
                    self._residual_seats_inspected_at.pop(seat_num, None)
                elif info.get("username") and info["username"] != username:
                    # 视口内明确读出新用户，残留作废
                    del self._residual_seats[seat_num]
                    self._residual_seats_inspected_at.pop(seat_num, None)
            else:
                # 视口外麦位：若该用户在快照中已不在任何麦位上，残留作废
                if not any(s.occupied and s.username == username for s in self.seats.values()):
                    del self._residual_seats[seat_num]
                    self._residual_seats_inspected_at.pop(seat_num, None)
        return {
            seat_num: name
            for seat_num, name in self._residual_seats.items()
            if seat_num in observed
        }

    async def _resolve_usernames(
        self,
        observed: Dict[int, Tuple[any, str, dict]],
        *,
        caller_holds_ui_session: bool = False,
    ) -> None:
        """补齐占用麦位的昵称：先沿用快照里已知的占位者，读不到再点头像弹窗。

        只在本轮确实没读到昵称时才沿用旧值 —— 无条件沿用会让座位上换人
        （label 里就是新昵称）永远 diff 不出来。

        沿用的旧值还不能与本轮别处的读数冲突：一个人同一时刻只占一个麦位。真机上
        Outlier 从 9 号换到 11 号（9 号那轮只读到占座、读不到昵称），沿用旧值就把
        同一个人钉在两个位子上，还把真正的换座整个吞掉 —— 全量重扫本该给出结论，
        不能拿旧快照替它猜答案。与别处冲突时不猜，改用唯一能认出人的手段：点头像
        读弹窗。

        冲突时谁让位，看的是证据的**来路**，不是谁先登记：
        - 本轮读到的身份（label 里的昵称/身份文字、或已经读过的弹窗）是这一屏的证据；
        - 从上一轮快照沿用的身份只是账面残留，本轮没有任何读数支持它。
        所以弹窗证据只否得掉「本轮读到」的身份。真机 09-29 11:40:5x：Outlier 从
        12 号换到 11 号，12 号还挂着残留渲染 —— 旧实现把快照里的 Outlier 沿用给
        12 号，再拿这条沿用值把 11 号的本轮弹窗证据判成 ghost 清空，可视范围内的
        换座被整个吞掉（快照原地不动、无座次表、无 move_seat 事件）。现在改成撤销
        那条没有证据的沿用值，把旧位子标成身份存疑（identity_contested）：被动观测
        一律不写、升级为全量重扫；权威重扫才把它按残留渲染清掉。

        撤销沿用值这条规则本身是对称的 —— 提交之后，"上一轮的位子"就换到了另一边，
        光靠证据来路判会让账本在两个位子之间来回掀翻。所以权威重扫清掉的残留位要记
        进 _residual_seats，并且只在"这个人本轮在别处确实还有位置"时继续成立。
        """
        residual_seats = self._prune_residual_records(observed)

        read_claims: Dict[str, int] = {
            info["username"]: seat_num
            for seat_num, (_desk, _side, info) in observed.items()
            if info.get("occupied") and info.get("username")
        }
        inherited_claims: Dict[str, int] = {}
        claimed = set(read_claims)
        pending = []
        for seat_num, (desk, side, info) in observed.items():
            if not info["occupied"] or info.get("username"):
                if info.get("occupied") and info.get("username") and info.get("label") == "管理":
                    self._record_room_admin(info["username"])
                continue
            residual_name = residual_seats.get(seat_num)
            if residual_name and self._placed_elsewhere(residual_name, seat_num, observed):
                # 处于冷却期内的已知残留位，无需且严禁反复点击头像弹窗（防止高频弹窗骚扰用户）
                last_inspect = self._residual_seats_inspected_at.get(seat_num, 0.0)
                if not self.cooldown_policy.is_residual_inspect_cooldown_expired(last_inspect):
                    self._mark_residual_seat(seat_num, info, residual_name)
                    continue
            old_slot = self.seats[seat_num]
            if old_slot.occupied and old_slot.username and old_slot.username not in claimed:
                info["username"] = old_slot.username
                claimed.add(old_slot.username)
                inherited_claims[old_slot.username] = seat_num
                if not info.get("label"):
                    if old_slot.label:
                        info["label"] = old_slot.label
                        info["is_owner"] = old_slot.is_owner
                    elif self._is_known_owner(old_slot.username):
                        info["label"] = "群主"
                        info["is_owner"] = True
                    elif self._is_known_room_admin(old_slot.username):
                        info["label"] = "管理"
                        info["is_owner"] = False
                if info.get("label") == "管理":
                    self._record_room_admin(info["username"])
                continue
            pending.append((seat_num, desk, side))

        if not pending:
            return

        async def _inspect_pending():
            for seat_num, desk, side in pending:
                username = await self.inspect_occupant(desk, side, seat_num)
                info = observed[seat_num][2]
                residual_name = residual_seats.get(seat_num)
                if residual_name:
                    if not self._placed_elsewhere(residual_name, seat_num, observed):
                        # 这个人别处已经没有位置了：这里就是他真实的落座处，
                        # 残留判定作废（宁可重扫一次，也不能把人从账上抹掉）
                        self._residual_seats.pop(seat_num, None)
                        self._residual_seats_inspected_at.pop(seat_num, None)
                    elif not username or username == residual_name:
                        self._mark_residual_seat(seat_num, info, residual_name)
                        self._residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
                        continue
                    else:
                        # 残留位上真坐了别人：作废残留记录，按正常落座处理
                        self._residual_seats.pop(seat_num, None)
                        self._residual_seats_inspected_at.pop(seat_num, None)
                if not username:
                    continue
                # 弹窗读出的人本轮在别处有**读到的**证据：该位为换座后的残留渲染
                # （ghost avatar）。一个人不能同时占两个位子，且弹窗证实头像是已落座
                # 之人而非他人，故该位实为空座，清除占座标记，避免虚增在座人数引发
                # 专注人数对账矛盾。
                if username in read_claims:
                    self.logger.warning(
                        f"Seat {seat_num}: popup shows {username!r}, who is already read on "
                        f"another seat this round; clearing ghost/residual occupant on seat {seat_num}"
                    )
                    self._mark_residual_seat(seat_num, info, username)
                    self._residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
                    continue
                # 冲突对象只是上一轮快照的沿用值：撤销它，旧位子的身份本轮无证据。
                stale_seat = inherited_claims.pop(username, None)
                if stale_seat is not None and stale_seat != seat_num:
                    claimed.discard(username)
                    stale_info = observed[stale_seat][2]
                    stale_info["username"] = None
                    stale_info["identity_contested"] = username
                    self.logger.warning(
                        f"Seat {seat_num}: popup identifies {username!r}; seat {stale_seat} only "
                        f"inherited them from the previous snapshot, so the move is unresolved "
                        f"there and the full rescan decides"
                    )
                info["username"] = username
                claimed.add(username)
                read_claims[username] = seat_num
                if not info.get("label"):
                    if self._is_known_owner(username):
                        info["label"] = "群主"
                        info["is_owner"] = True
                    elif self._is_known_room_admin(username):
                        info["label"] = "管理"
                        info["is_owner"] = False
                if info.get("label") == "管理":
                    self._record_room_admin(username)

        if caller_holds_ui_session:
            await _inspect_pending()
        else:
            async with self._ui_session("seat_inspect"):
                await _inspect_pending()

    def _colliding_usernames(
        self, observed: Dict[int, Tuple[any, str, dict]]
    ) -> Dict[str, List[int]]:
        """同一次观测里被两个及以上麦位读到的昵称 -> 号位列表。

        一个人同一时刻只占一个麦位，所以这是读数自相矛盾（座位号错位、或读到同一个
        人的两个渲染），代码分不出哪一处才是真的。
        """
        seen: Dict[str, List[int]] = {}
        for seat_num, (_desk, _side, info) in observed.items():
            if not info.get("occupied"):
                continue
            username = info.get("username")
            if username:
                seen.setdefault(username, []).append(seat_num)
        return {name: nums for name, nums in seen.items() if len(nums) > 1}

    def _apply_snapshot(
        self,
        observed: Dict[int, Tuple[any, str, dict]],
        *,
        clearable: Optional[Set[int]] = None,
    ) -> None:
        """落快照。

        clearable 为 None 表示权威路径（全量重扫读过全部麦位）：观测到的明确空座
        即可判为下座。被动观测必须显式给出可清空的号位（视口内配对换座的旧位）——
        其余读数只能补占座，绝不能凭局部读数把人推平。

        「明确空座」由 DOM 证据定义（见 _judge_empty），不再看像素高度：滑出视口或
        折叠的麦位读不到任何空座证据，走到这里时 is_empty 本来就是 False。

        最后一道闸：一次观测里同一个人读到两个位子上，按证据强度（房主身份、
        显式 label、证据权重）决出真实落座处，冲突麦位作为残留渲染清空，
        严禁将同一人计为两座引发与专注人数背离。
        """
        colliding = self._colliding_usernames(observed)
        winner_seats: Dict[str, int] = {}
        for name, seat_nums in colliding.items():
            self.logger.warning(
                f"Seat identity conflict: {name!r} read on seats {sorted(seat_nums)} "
                f"in one observation; resolving to seat with stronger evidence"
            )

            def _score(s_num: int) -> tuple:
                _desk, _side, s_info = observed[s_num]
                is_owner_score = 2 if s_info.get("is_owner") else 0
                has_label = 1 if bool(s_info.get("label", "").strip()) else 0
                weight = self._evidence_weight(s_info)
                return (is_owner_score, has_label, weight, s_num)

            winner_seats[name] = max(seat_nums, key=_score)

        for seat_num, (desk, side, info) in observed.items():
            slot = self.seats[seat_num]
            if info.get("identity_contested") and clearable is None:
                # 权威路径（全量重扫读过全部麦位）：这个位子本轮没有自己的身份证据，
                # 而快照挂在它上面的人已被弹窗落在别处 —— 它就是换座后的残留渲染。
                # 留着不改就等于一人两座，在座数凭空 +1，下一轮专注人数对账又要重扫。
                self.logger.warning(
                    f"Seat {seat_num}: residual render after an in-viewport move, clearing "
                    f"(the occupant is accounted for on another seat this round)"
                )
                slot.occupied = False
                slot.username = None
                slot.label = info.get("label", "")
                slot.is_owner = False
                info["occupied"] = False
                info["is_empty"] = True
                # 记下这笔残留：下一轮它还渲染成占座，不能再跟真正的落座处抢身份
                self._residual_seats[seat_num] = str(info.get("identity_contested") or "")
                self._residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
                continue
            if info["occupied"]:
                username = info.get("username")
                if username in colliding:
                    if seat_num == winner_seats[username]:
                        slot.occupied = True
                        slot.username = username
                        self._apply_seat_role(slot, info, username)
                    else:
                        self.logger.warning(
                            f"Seat {seat_num}: clearing ghost duplicate of {username!r} "
                            f"(retained on seat {winner_seats[username]})"
                        )
                        slot.occupied = False
                        slot.username = None
                        slot.label = ""
                        slot.is_owner = False
                        info["occupied"] = False
                        info["is_empty"] = True
                        info["username"] = None
                        info["label"] = ""
                        info["is_owner"] = False
                        # 记下这笔残留：下一轮它还渲染成占座，不能再反复弹窗
                        self._residual_seats[seat_num] = username
                        self._residual_seats_inspected_at[seat_num] = self.cooldown_policy.now()
                    continue
                slot.occupied = True
                slot.username = username
                self._apply_seat_role(slot, info, username)
            elif info.get("is_empty"):
                if clearable is None or seat_num in clearable:
                    slot.occupied = False
                    slot.username = None
                    slot.label = info.get("label", "")
                    slot.is_owner = False
                elif slot.occupied:
                    self.logger.debug(
                        f"Seat {seat_num}: read as empty but not clearable "
                        f"(clearable={clearable}); "
                        f"keeping known occupant {slot.username!r}"
                    )
            else:
                # 不可见/稀疏内容状态（例如仅有 leftBottomView，出了视口或被折叠）
                # 严禁将不可见误认为下座！如果之前是被占用状态，必须保留原占座信息，防止触发死循环扫描
                pass

    async def _sync_desks(
        self,
        desk_wrappers: list,
        trigger_source: str,
        focus_count: Optional[int],
        *,
        caller_holds_ui_session: bool = False,
        notify_after: Optional[int] = None,
    ) -> Tuple[bool, Set[Tuple[int, str]]]:
        """映射 -> 读麦位 -> 补昵称 -> 分类 -> 落快照 -> diff -> 通知。

        返回 (快照是否有变更, 去向不明需要全量扫描的变更指纹)。

        被动观测与背离重扫共用这一段；区别只在触发源文案、是否自己拿 ui_session
        （重扫已在外层持有，asyncio.Lock 不可重入）以及通知里的人数取值。
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

        old_slots = {k: v.copy() for k, v in self.seats.items()}

        await self._resolve_usernames(
            observed, caller_holds_ui_session=caller_holds_ui_session
        )

        # 只有「看得明白」的变更才落快照：有人消失/凭空出现/同位换人都说明影响可能
        # 落在看不见的麦位上 —— 那种读数既不写快照，也不当作没发生，交给全量扫描定夺。
        writable, clearable, unexplained = self._plan_observation_changes(old_slots, observed)
        to_apply = {num: item for num, item in observed.items() if num in writable}
        if to_apply:
            self._apply_snapshot(to_apply, clearable=clearable)

        has_changes, changed_users, seat_info = self._compute_diff(
            old_slots, self.seats, set(to_apply.keys())
        )

        if has_changes:
            self.logger.info(
                self.format_3row_layout(
                    trigger_source=trigger_source,
                    focus_count=focus_count,
                    changed_seats=self._changed_seat_numbers(
                        old_slots, self.seats, set(to_apply.keys())
                    ),
                )
            )

            if changed_users:
                from ushareiplay.managers.command_manager import CommandManager
                if notify_after is None:
                    # 被动观测没有新的人数，用最新在座数作为 after
                    notify_after = sum(1 for s in self.seats.values() if s.occupied)
                await CommandManager.instance().notify_focus_count_change(
                    self._last_focus_count, notify_after, changed_users=changed_users, seat_info=seat_info
                )

        if focus_count is not None:
            self._last_focus_count = focus_count

        if unexplained:
            self.logger.debug(f"[seat-obs] 变更去向不明 {sorted(unexplained)}")

        return has_changes, unexplained

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

        async with self._lock:
            has_changes, unexplained = await self._sync_desks(
                desk_wrappers,
                "可视区域变更",
                current_focus_count,
                caller_holds_ui_session=False,
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
        """按专注人数对账：同一个取值最多触发一次全量重扫。

        被动观测只能看到部分麦位，它的在座数与专注人数不一致是常态，不能作为
        「再扫一次」的依据；只有专注人数这个取值本身发生变化（有人进来/离开专注）
        才值得重新对一次账。人数没变时即使快照仍然对不上也绝不重复展开。
        """
        if target_focus is None:
            return False
        if target_focus == self._reconciled_focus_count:
            return False
        # 先登记再重扫：重扫耗时十几秒，期间事件轮询还会反复进来
        self._reconciled_focus_count = target_focus

        total_seated = sum(1 for s in self.seats.values() if s.occupied)
        if total_seated == target_focus:
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
            self._reconciled_focus_count = None
        return attempted and self._last_rescan_ok

    async def _resolve_unexplained_changes(
        self,
        unexplained: Set[Tuple[int, str]],
        target_focus: Optional[int],
        *,
        already_scanned: bool = False,
    ) -> bool:
        """视口里出现去向不明的变更 → 全量扫描一遍，取最最最新的座位信息。

        抑制规则：同一份读数指纹只扫一次 —— 扫过就说明最新信息已经拿到了；如果扫完
        读数还是这样，说明这份读数在该渲染下不可信（例如折叠视口读不到某个麦位），
        不能无限重复展开。读数一旦变化（新的指纹）就重新扫；读数恢复一致时清空指纹，
        同样的异常下次还会重新触发。
        """
        if not unexplained:
            self._scanned_seat_change_fingerprint = None
            return False
        fingerprint = frozenset(unexplained)
        if fingerprint == self._scanned_seat_change_fingerprint:
            return False
        if already_scanned:
            # 本轮已经因为专注人数对账全量扫过了，这份读数已经被那次扫描服务过
            self._scanned_seat_change_fingerprint = fingerprint
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
        if not self.cooldown_policy.is_cooldown_expired(
            self._last_rescan_time,
            last_rescan_ok=self._last_rescan_ok,
            consistency_retry_due=self._consistency_retry_due,
        ):
            return False
        if fingerprint is not None:
            self._scanned_seat_change_fingerprint = fingerprint
        self._last_rescan_time = self.cooldown_policy.now()
        self.logger.info(reason)
        await self.expand_rescan_and_collapse(target_focus)
        if not self._last_rescan_ok and fingerprint is not None:
            # 扫描没落地（展开失败/半截快照）：撤掉指纹，留给下一轮重试
            self._scanned_seat_change_fingerprint = None
        # 返回值表示「扫描确实执行过」，成败一律看 _last_rescan_ok
        return True

    @staticmethod
    def _evidence_weight(info: dict) -> int:
        """一份读数对「这个位子到底是谁 / 到底空不空」的回答力度。

        占座且有昵称 > 占座但没读到昵称 > 明确空座 > 什么都没读到。
        """
        if info.get("occupied"):
            return 3 if info.get("username") else 2
        if info.get("is_empty"):
            return 1
        return 0

    async def _scan_all_rows_expanded(self, initial_desks: list) -> Dict[int, Tuple[any, str, dict]]:
        """
        在展开状态下执行双向全量扫描：
        1. 滑到第一排（Row 0），观测前两排（1~8号麦位）并解析未识别昵称；
        2. 滑到第三排（Row 2），观测后两排（5~12号麦位）并解析未识别昵称；
        3. 合并两次观测结果，确保 1~12 号麦位全部完整覆盖，最后滑回第一排复位。
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
        await self._resolve_usernames(top_observed, caller_holds_ui_session=True)
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
                if shared_name not in self._claimed_usernames(bottom_observed):
                    item[2]["username"] = shared_name
                    if not item[2].get("label") and shared[2].get("label"):
                        item[2]["label"] = shared[2]["label"]
                        item[2]["is_owner"] = shared[2].get("is_owner", False)

        await self._resolve_usernames(bottom_observed, caller_holds_ui_session=True)

        for seat_num, item in bottom_observed.items():
            if seat_num not in observed_all:
                observed_all[seat_num] = item
            elif self._evidence_weight(item[2]) > self._evidence_weight(observed_all[seat_num][2]):
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
        主动展开面板 -> 全量双向重扫 12 个麦位（滑到顶扫前两排，滑到底扫后两排） -> 复位并收起。
        """
        if not self.handler:
            return False

        self._last_rescan_time = time.monotonic()
        # 记为「没落地」：中途失败/半截快照时调用方要据此保留闸门、下轮重试
        self._last_rescan_ok = False
        # 这一扫就是那次补扫本身：先撤销欠账，结不结由 _verify_focus_consistency 说
        self._consistency_retry_due = False

        async with self._lock, self._ui_session("seat_expansion"):
            try:
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

                # 双向扫描覆盖全部 3 排麦位（顶部前两排与底部后两排）
                observed = await self._scan_all_rows_expanded(seat_desks)
                if not observed:
                    return False

                old_slots = {k: v.copy() for k, v in self.seats.items()}
                # 权威路径：两个相位把 12 个麦位都读过，明确空座即可判下座
                self._apply_snapshot(observed)
                self._last_rescan_ok = True

                has_changes, changed_users, seat_info = self._compute_diff(
                    old_slots, self.seats, set(observed.keys())
                )

                # 重扫是十几秒的主动行为，落地就得给出结论：没有变更也打印，否则没人
                # 能判断这次到底读到了什么（真机 23:00:0x：扫完一个字节都没输出，
                # 「1 个专注」到底坐在哪无从核对）。
                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="专注人数背离展开重扫",
                        focus_count=target_focus_count,
                        changed_seats=self._changed_seat_numbers(
                            old_slots, self.seats, set(observed.keys())
                        ),
                    )
                )

                if changed_users:
                    from ushareiplay.managers.command_manager import CommandManager
                    await CommandManager.instance().notify_focus_count_change(
                        self._last_focus_count,
                        target_focus_count,
                        changed_users=changed_users,
                        seat_info=seat_info,
                    )

                if target_focus_count is not None:
                    self._last_focus_count = target_focus_count

                # 重扫的结论必须跟房间唯一的硬数字自洽，否则这次账没对上
                self._verify_focus_consistency(observed, target_focus_count)

                return has_changes

            except Exception:
                self.logger.error(f"Error during expand_rescan_and_collapse: {traceback.format_exc()}")
                return False
            finally:
                try:
                    await self.seat_ui.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats after rescan: {e}")

    @staticmethod
    def _scan_fingerprint(observed: Dict[int, Tuple[any, str, dict]]) -> frozenset:
        """一次重扫的读数指纹（号位 + 占/空 + label 原文），不含坐标。

        同样的指纹说明面板没有给出任何新信息：这时再展开收起一次也只会得到同一份
        答案，补扫就没有意义。
        """
        return frozenset(
            (
                seat_num,
                bool(info.get("occupied")),
                bool(info.get("is_empty")),
                (info.get("label") or "").strip(),
            )
            for seat_num, (_desk, _side, info) in observed.items()
        )

    def _verify_focus_consistency(
        self, observed: Dict[int, Tuple[any, str, dict]], target_focus_count: Optional[int]
    ) -> None:
        """重扫落地不等于对上账：结论与专注人数矛盾时把账重新挂回去，欠一次补扫。

        旧实现「先登记已对账、再扫描」，而且只在扫描**失败**时撤登记 —— 于是扫完
        自相矛盾（真机 09-27 22:29:31：读出 4 个在座，同一行里的专注人数是 3，9 号位
        挂着已经下座的残留 label）也算成功，这份错表格要用到专注人数下次变化为止。

        补扫是有信息量的：展开收起会逼面板重绘，残留 label 通常第二遍就清了。但
        读数与上一次完全相同时不再补扫 —— 同样的 DOM 再扫还是同样答案，只能等新
        信息（下一次人数变化/麦位变更），不能拿死循环换安心。
        """
        if target_focus_count is None:
            return

        unresolved = [
            seat_num
            for seat_num, (_desk, _side, info) in observed.items()
            if not info.get("occupied") and not info.get("is_empty")
        ]
        if len(observed) != 12 or unresolved:
            # 这一轮没把 12 个位子都读出确定结论，「在座数 != 专注数」不算矛盾：
            # 差值可能只是没看见的位子，不能据此判定表格出错、更不能据此反复展开。
            self._last_scan_fingerprint = None
            return

        fingerprint = self._scan_fingerprint(observed)
        same_as_last = fingerprint == self._last_scan_fingerprint
        self._last_scan_fingerprint = fingerprint

        seated = sum(1 for slot in self.seats.values() if slot.occupied)
        if seated == target_focus_count:
            self._consistency_retry_due = False
            return

        seated_nums = sorted(n for n, s in self.seats.items() if s.occupied)
        if same_as_last:
            self._consistency_retry_due = False
            self.logger.warning(
                f"Rescan still disagrees with focus count ({seated} seated vs {target_focus_count}) "
                f"with byte-identical readings; not re-scanning — same DOM yields same answer, "
                f"waiting for new information. seated seats: {seated_nums}"
            )
            return

        self._consistency_retry_due = True
        # 账没对上：撤掉「这个人数已经对过账」的登记，让下一轮按补扫冷却再来一次
        self._reconciled_focus_count = None
        self.logger.warning(
            f"Rescan is not self-consistent: {seated} seats occupied but focus count is "
            f"{target_focus_count} (occupied: {seated_nums}); ledger reopened, "
            f"will re-scan after {self.cooldown_policy.consistency_rescan_cooldown}s"
        )

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

        selector = self._element_selector("seat_desk") or "cn.soulapp.android:id/userRoot"
        if selector.startswith("//"):
            nodes = root.xpath(selector)
        else:
            nodes = root.xpath(f"//*[@resource-id='{selector}']")

        desk_wrappers = [ElementWrapper(node, self.handler, "seat_desk") for node in nodes]
        if not desk_wrappers:
            return {}

        async with self._lock:
            observed = self._read_visible_seats(desk_wrappers, band=band)
            if not observed:
                return {}

            old_slots = {k: v.copy() for k, v in self.seats.items()}

            # 沿用快照中已知的昵称
            for seat_num, (desk, side, info) in observed.items():
                if info["occupied"] and not info.get("username"):
                    old_slot = self.seats.get(seat_num)
                    if old_slot and old_slot.occupied and old_slot.username:
                        info["username"] = old_slot.username

            # 视口可见麦位具有直接 DOM 证据，明确空座允许清空旧快照
            self._apply_snapshot(observed, clearable=set(observed.keys()))

            has_changes, changed_users, seat_info = self._compute_diff(
                old_slots, self.seats, set(observed.keys())
            )

            if has_changes:
                self.logger.info(
                    self.format_3row_layout(
                        trigger_source="视口同步",
                        focus_count=self._last_focus_count,
                        changed_seats=self._changed_seat_numbers(
                            old_slots, self.seats, set(observed.keys())
                        ),
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

        stale = [
            num
            for num, slot in self.seats.items()
            if num != seat_number
            and slot.occupied
            and (slot.is_owner or slot.username in {owner_username, "群主"})
        ]
        for num in stale:
            old = self.seats[num]
            old.occupied = False
            old.username = None
            old.label = ""
            old.is_owner = False

        slot = self.seats.get(seat_number)
        if slot:
            slot.occupied = True
            slot.username = owner_username
            slot.label = "群主"
            slot.is_owner = True

        current = self._last_focus_count
        if current is None:
            try:
                from ushareiplay.state.room_state import RoomState
                current = RoomState.instance().focus_count
            except Exception as e:
                self.logger.debug(f"RoomState focus_count unavailable, falling back to seated count: {e}")
                current = None

        if current is not None:
            new_count = current if stale else current + 1
        else:
            new_count = sum(1 for s in self.seats.values() if s.occupied)

        self._last_focus_count = new_count
        self._reconciled_focus_count = new_count

        try:
            from ushareiplay.state.room_state import RoomState
            RoomState.instance().focus_count = new_count
        except Exception as e:
            # 对账闸门读的是 _reconciled_focus_count 与快照座位数，不读 RoomState，
            # 所以这里写失败不会误触发重扫；但 RoomState 会停在旧值，必须留痕。
            self.logger.warning(f"Failed to write RoomState.focus_count={new_count} after seating: {e}")

