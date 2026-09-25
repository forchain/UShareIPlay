from __future__ import annotations

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import ClassVar, Dict, List, Optional, Set, Tuple

from ushareiplay.core.element_wrapper import ElementWrapper
from ushareiplay.core.singleton import Singleton


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

    def __init__(self, handler=None):
        self.handler = handler
        self._logger = None
        self._controller = None
        self._seat_ui = None
        # 全局 1~12 号位快照
        self.seats: Dict[int, SeatSlot] = {
            i: SeatSlot(seat_number=i) for i in range(1, 13)
        }
        self._last_focus_count: Optional[int] = None
        self._lock = asyncio.Lock()

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
            self._seat_ui = SeatUIManager(self.handler)
        return self._seat_ui

    def clear(self):
        """重置所有麦位状态"""
        self.seats = {i: SeatSlot(seat_number=i) for i in range(1, 13)}
        self._last_focus_count = None
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
        if not isinstance(config, dict):
            return None

        elements = config.get("elements")
        if not isinstance(elements, dict):
            soul = config.get("soul")
            elements = soul.get("elements") if isinstance(soul, dict) else None

        selector = elements.get(element_key) if isinstance(elements, dict) else None
        if isinstance(selector, str) and selector.strip():
            return selector.strip()
        return None

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
            xpath = f".//*[@resource-id='{selector}']"
            try:
                return desk.find_child_element(xpath)
            except Exception:
                return None

        finder = getattr(self.handler, "element_finder", None)
        if finder is None:
            return None
        return finder.find_child_element(desk, element_key, log_failure=False)

    def _is_seat_occupied(self, desk, side: str) -> bool:
        return self._find_child_element(desk, f"{side}_state") is not None

    def format_3row_layout(self, trigger_source: str = "可视区域变更") -> str:
        """
        输出符合物理现实效果的直观快照：一排两张桌，每张桌两个人，共三排。
        """
        def format_seat(num: int) -> str:
            slot = self.seats.get(num)
            if not slot or not slot.occupied:
                return f"[{num}号: 空闲]"
            if slot.is_owner:
                name = f"群主({slot.username})" if slot.username and slot.username != "群主" else "群主"
                return f"[{num}号: {name}]"
            name = slot.username or slot.label or "已占用"
            return f"[{num}号: {name}]"

        lines = [
            f"[FocusSeatObservation] 专注麦位状态变更 (触发源: {trigger_source}):",
            f"  第一排: {format_seat(1)} {format_seat(2)}  |  {format_seat(3)} {format_seat(4)}",
            f"  第二排: {format_seat(5)} {format_seat(6)}  |  {format_seat(7)} {format_seat(8)}",
            f"  第三排: {format_seat(9)} {format_seat(10)}  |  {format_seat(11)} {format_seat(12)}",
        ]
        return "\n".join(lines)

    def map_desks_to_indices(self, desk_wrappers: list) -> List[Tuple[int, any]]:
        """
        根据桌子中的麦位编号、标签或坐标，将当前可见的 desk_wrappers 映射为其全局 desk_index (0..5)。
        - Row 0 (第一排): desk 0 (seats 1,2), desk 1 (seats 3,4)
        - Row 1 (第二排): desk 2 (seats 5,6), desk 3 (seats 7,8)
        - Row 2 (第三排): desk 4 (seats 9,10), desk 5 (seats 11,12)

        优先用空座位上的麦位编号锚定；读不到编号（例如可视桌位全满）时退回坐标
        聚类，此时**假设可视桌位从 desk 0 起连续可见** —— 面板被滚动、只露出
        中后排时坐标兜底会把桌位错配。被动观测不滚动面板，因此该兜底只在
        视口对齐默认位置时可信。
        """
        result = []
        unresolved = []

        for idx, desk in enumerate(desk_wrappers):
            desk_idx = self._detect_desk_index_from_labels(desk)
            if desk_idx is not None and 0 <= desk_idx <= 5:
                result.append((desk_idx, desk))
            else:
                unresolved.append((idx, desk))

        if not unresolved:
            # 按 desk_index 升序排序
            result.sort(key=lambda item: item[0])
            return result

        # 辅助策略：基于 bounds 坐标排序聚类
        assigned_indices = {r[0] for r in result}
        sorted_unresolved = sorted(unresolved, key=lambda item: self._desk_sort_key(item[1]))

        avail_indices = [i for i in range(6) if i not in assigned_indices]
        for (orig_idx, desk), desk_idx in zip(sorted_unresolved, avail_indices):
            result.append((desk_idx, desk))

        result.sort(key=lambda item: item[0])
        return result

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
        if not label_text.isdigit():
            return None
        seat_num = int(label_text)
        if not 1 <= seat_num <= 12:
            return None
        return seat_num

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

    def _extract_seat_info(self, desk, side: str) -> dict:
        occupied = self._is_seat_occupied(desk, side)
        label = self._get_label_text(desk, side)

        is_owner = (label == "群主")
        username = None
        if is_owner:
            username = "群主"
        elif label and not label.isdigit() and label not in ("管理", "已占用", "点击入座"):
            username = label

        return {
            "occupied": occupied,
            "label": label,
            "is_owner": is_owner,
            "username": username,
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

    async def inspect_occupant(self, desk, side: str, seat_number: int) -> Optional[str]:
        """点击麦位弹窗读取用户昵称并立即 press_back 关闭弹窗"""
        if not self.handler:
            return None

        self.logger.info(f"Inspecting occupant on seat {seat_number} ({side} side)")
        try:
            target_element = self._find_child_element(desk, f"{side}_state")
            if target_element is None:
                target_element = self._find_child_element(desk, f"{side}_seat")
            self._click_seat_avatar(desk, side, target_element)

            await asyncio.sleep(0.3)

            username = None
            if hasattr(self.handler, "element_finder"):
                _found_key, name_elem = self.handler.element_finder.wait_for_any_element(
                    ["souler_name", "user_name"], timeout=1.5
                )
                if name_elem and hasattr(name_elem, "text") and name_elem.text:
                    username = name_elem.text.strip()

            return username

        except Exception as e:
            self.logger.error(f"Error inspecting occupant on seat {seat_number}: {e}")
            return None
        finally:
            try:
                if hasattr(self.handler, "key_actions"):
                    self.handler.key_actions.press_back()
                await asyncio.sleep(0.2)
            except Exception:
                pass

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

            if old.occupied != new.occupied or old.username != new.username or old.label != new.label:
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

    def _read_visible_seats(self, desk_wrappers: list) -> Dict[int, Tuple[any, str, dict]]:
        """把可见桌位读成 {seat_number: (desk, side, info)}。"""
        observed: Dict[int, Tuple[any, str, dict]] = {}
        for desk_idx, desk in self.map_desks_to_indices(desk_wrappers):
            for side, offset in (("left", 1), ("right", 2)):
                seat_num = desk_idx * 2 + offset
                observed[seat_num] = (desk, side, self._extract_seat_info(desk, side))
        return observed

    async def _resolve_usernames(self, observed: Dict[int, Tuple[any, str, dict]]) -> None:
        """补齐占用麦位的昵称：先沿用快照里已知的占位者，读不到再点头像弹窗。

        只在本轮确实没读到昵称时才沿用旧值 —— 无条件沿用会让座位上换人
        （label 里就是新昵称）永远 diff 不出来。
        """
        pending = []
        for seat_num, (desk, side, info) in observed.items():
            if not info["occupied"] or info.get("username"):
                continue
            old_slot = self.seats[seat_num]
            if old_slot.occupied and old_slot.username:
                info["username"] = old_slot.username
                continue
            pending.append((seat_num, desk, side))

        for seat_num, desk, side in pending:
            username = await self.inspect_occupant(desk, side, seat_num)
            if username:
                observed[seat_num][2]["username"] = username

    def _apply_snapshot(self, observed: Dict[int, Tuple[any, str, dict]]) -> None:
        for seat_num, (desk, side, info) in observed.items():
            slot = self.seats[seat_num]
            slot.occupied = info["occupied"]
            slot.username = info.get("username")
            slot.label = info.get("label", "")
            slot.is_owner = info.get("is_owner", False)

    async def _sync_desks(
        self,
        desk_wrappers: list,
        trigger_source: str,
        focus_count: Optional[int],
        *,
        caller_holds_ui_session: bool = False,
        notify_after: Optional[int] = None,
    ) -> bool:
        """映射 -> 读麦位 -> 补昵称 -> 落快照 -> diff -> 通知。

        被动观测与背离重扫共用这一段；区别只在触发源文案、是否自己拿 ui_session
        （重扫已在外层持有，asyncio.Lock 不可重入）以及通知里的人数取值。
        """
        observed = self._read_visible_seats(desk_wrappers)
        if not observed:
            return False

        old_slots = {k: v.copy() for k, v in self.seats.items()}

        if caller_holds_ui_session:
            await self._resolve_usernames(observed)
        else:
            async with self._ui_session("seat_inspect"):
                await self._resolve_usernames(observed)

        self._apply_snapshot(observed)

        has_changes, changed_users, seat_info = self._compute_diff(
            old_slots, self.seats, set(observed.keys())
        )

        if has_changes:
            self.logger.info(self.format_3row_layout(trigger_source=trigger_source))

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

        return has_changes

    async def observe_visible_desks(
        self, desk_wrappers: list, current_focus_count: Optional[int] = None
    ) -> bool:
        """被动观测当前可见的桌位，检测变动并维护全局快照"""
        if not desk_wrappers:
            return False

        async with self._lock:
            return await self._sync_desks(
                desk_wrappers,
                "可视区域变更",
                current_focus_count,
                caller_holds_ui_session=False,
            )

    async def on_focus_count(self, before: Optional[int], current_focus_count: int) -> bool:
        """专注人数发生变化时调用。如果人数与当前在座人数背离，打破被动规则主动展开全量扫描。"""
        total_seated = sum(1 for s in self.seats.values() if s.occupied)
        divergence = (current_focus_count != total_seated)

        if divergence:
            self.logger.info(
                f"Focus divergence detected: focus_count={current_focus_count}, known_seated={total_seated}. "
                "Triggering active expansion rescan."
            )
            return await self.expand_rescan_and_collapse(current_focus_count)
        else:
            self._last_focus_count = current_focus_count
            return False

    async def expand_rescan_and_collapse(self, target_focus_count: int) -> bool:
        """
        主动展开面板 -> 全量重扫 12 个麦位 -> 立即收起恢复聊天视口。
        """
        if not self.handler:
            return False

        async with self._lock, self._ui_session("seat_expansion"):
            try:
                # 用规范 helper：展开失败或桌位不足 6 张都返回 None，避免半截快照
                seat_desks = await self.seat_ui.expand_and_find_desks()
                if not seat_desks:
                    self.logger.warning("Failed to expand seats for full rescan")
                    return False

                return await self._sync_desks(
                    seat_desks,
                    "专注人数背离展开重扫",
                    target_focus_count,
                    caller_holds_ui_session=True,
                    notify_after=target_focus_count,
                )

            except Exception:
                self.logger.error(f"Error during expand_rescan_and_collapse: {traceback.format_exc()}")
                return False
            finally:
                try:
                    await self.seat_ui.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats after rescan: {e}")
