from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import traceback
from typing import Dict, List, Optional, Set, Tuple

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

    async def acquire_ui_lock(self, reason: str = "seat_observation"):
        ctrl = self.controller
        if ctrl and hasattr(ctrl, "acquire_ui_lock"):
            try:
                await ctrl.acquire_ui_lock(reason)
            except Exception as e:
                self.logger.debug(f"acquire_ui_lock failed: {e}")

    def release_ui_lock(self, reason: str = "seat_observation"):
        ctrl = self.controller
        if ctrl and hasattr(ctrl, "release_ui_lock"):
            try:
                ctrl.release_ui_lock(reason)
            except Exception as e:
                self.logger.debug(f"release_ui_lock failed: {e}")

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

    def _detect_desk_index_from_labels(self, desk) -> Optional[int]:
        # 显式 desk_index 属性（用于测试及桩对象）
        if hasattr(desk, "desk_index") and isinstance(desk.desk_index, int):
            return desk.desk_index

        for side in ("left", "right"):
            label_text = self._get_label_text(desk, side)
            if label_text:
                match = re.search(r"\b([1-9]|1[0-2])\b", label_text)
                if match:
                    seat_num = int(match.group(1))
                    return (seat_num - 1) // 2
        return None

    def _get_label_text(self, desk, side: str) -> str:
        key = f"{side}_label"
        if hasattr(desk, "find_child_element"):
            elem = desk.find_child_element(key)
            if elem and hasattr(elem, "text"):
                return elem.text or ""
        elif hasattr(self.handler, "element_finder"):
            elem = self.handler.element_finder.find_child_element(desk, key, log_failure=False)
            if elem and hasattr(elem, "text"):
                return elem.text or ""
        return ""

    def _extract_seat_info(self, desk, side: str, seat_number: int) -> dict:
        state_key = f"{side}_state"
        label_key = f"{side}_label"

        occupied = False
        label = ""

        if hasattr(desk, "find_child_element"):
            state_elem = desk.find_child_element(state_key)
            label_elem = desk.find_child_element(label_key)
            occupied = bool(state_elem)
            label = getattr(label_elem, "text", "") or ""
        elif hasattr(self.handler, "element_finder"):
            state_elem = self.handler.element_finder.find_child_element(desk, state_key, log_failure=False)
            label_elem = self.handler.element_finder.find_child_element(desk, label_key, log_failure=False)
            occupied = bool(state_elem)
            label = getattr(label_elem, "text", "") or ""

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

    async def inspect_occupant(self, desk, side: str, seat_number: int) -> Optional[str]:
        """点击麦位弹窗读取用户昵称并立即 press_back 关闭弹窗"""
        if not self.handler:
            return None

        self.logger.info(f"Inspecting occupant on seat {seat_number} ({side} side)")
        try:
            target_element = None
            if hasattr(desk, "find_child_element"):
                target_element = desk.find_child_element(f"{side}_state") or desk.find_child_element(f"{side}_seat")
            elif hasattr(self.handler, "element_finder"):
                target_element = self.handler.element_finder.find_child_element(desk, f"{side}_state", log_failure=False)
                if not target_element:
                    target_element = self.handler.element_finder.find_child_element(desk, f"{side}_seat", log_failure=False)

            if target_element:
                if hasattr(target_element, "click"):
                    target_element.click()
            elif hasattr(desk, "bounds") and desk.bounds:
                bounds = desk.bounds
                w = bounds["width"]
                h = bounds["height"]
                x = bounds["x"] + (w // 4 if side == "left" else (3 * w) // 4)
                y = bounds["y"] + h // 2
                if hasattr(self.handler, "gesture_handler") and hasattr(self.handler.gesture_handler, "_perform_click_at"):
                    self.handler.gesture_handler._perform_click_at(x, y)

            await asyncio.sleep(0.3)

            username = None
            if hasattr(self.handler, "element_finder"):
                found_key, name_elem = self.handler.element_finder.wait_for_any_element(
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
        changed_users = []
        seat_info = {}
        has_changes = False

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
                seat_info[new.username] = {
                    "seat_number": num,
                    "action": "sit_down",
                }
            # 检测用户离座
            elif old.occupied and not new.occupied and old.username:
                if old.username not in changed_users:
                    changed_users.append(old.username)
                seat_info[old.username] = {
                    "seat_number": num,
                    "action": "leave",
                }
            # 检测换人
            elif old.occupied and new.occupied and old.username and new.username and old.username != new.username:
                if old.username not in changed_users:
                    changed_users.append(old.username)
                seat_info[old.username] = {"seat_number": num, "action": "leave"}

                if new.username not in changed_users:
                    changed_users.append(new.username)
                seat_info[new.username] = {"seat_number": num, "action": "sit_down"}

        return has_changes, changed_users, seat_info

    async def observe_visible_desks(
        self, desk_wrappers: list, current_focus_count: Optional[int] = None
    ) -> bool:
        """被动观测当前可见的桌位，检测变动并维护全局快照"""
        if not desk_wrappers:
            return False

        async with self._lock:
            desk_mappings = self.map_desks_to_indices(desk_wrappers)
            old_slots = {k: v.copy() for k, v in self.seats.items()}
            pending_inspections = []
            observed_seats_data = {}

            for desk_idx, desk in desk_mappings:
                left_seat_num = desk_idx * 2 + 1
                right_seat_num = desk_idx * 2 + 2

                left_info = self._extract_seat_info(desk, "left", left_seat_num)
                right_info = self._extract_seat_info(desk, "right", right_seat_num)

                observed_seats_data[left_seat_num] = (desk, "left", left_info)
                observed_seats_data[right_seat_num] = (desk, "right", right_info)

            for seat_num, (desk, side, info) in observed_seats_data.items():
                old_slot = self.seats[seat_num]
                if info["occupied"]:
                    if old_slot.occupied and old_slot.username:
                        info["username"] = old_slot.username
                    elif not info.get("username"):
                        pending_inspections.append((seat_num, desk, side))

            if pending_inspections:
                await self.acquire_ui_lock("seat_inspect")
                try:
                    for seat_num, desk, side in pending_inspections:
                        username = await self.inspect_occupant(desk, side, seat_num)
                        if username:
                            desk, side, info = observed_seats_data[seat_num]
                            info["username"] = username
                finally:
                    self.release_ui_lock("seat_inspect")

            for seat_num, (desk, side, info) in observed_seats_data.items():
                slot = self.seats[seat_num]
                slot.occupied = info["occupied"]
                slot.username = info.get("username")
                slot.label = info.get("label", "")
                slot.is_owner = info.get("is_owner", False)

            has_changes, changed_users, seat_info = self._compute_diff(
                old_slots, self.seats, set(observed_seats_data.keys())
            )

            if has_changes:
                log_msg = self.format_3row_layout(trigger_source="可视区域变更")
                self.logger.info(log_msg)

                if changed_users:
                    from ushareiplay.managers.command_manager import CommandManager
                    total_seated = sum(1 for s in self.seats.values() if s.occupied)
                    await CommandManager.instance().notify_focus_count_change(
                        self._last_focus_count, total_seated, changed_users=changed_users, seat_info=seat_info
                    )

            if current_focus_count is not None:
                self._last_focus_count = current_focus_count

            return has_changes

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

        async with self._lock:
            await self.acquire_ui_lock("seat_expansion")
            try:
                expanded = await self.seat_ui.expand_seats()
                if not expanded:
                    self.logger.warning("Failed to expand seats for full rescan")
                    return False

                await asyncio.sleep(0.5)

                seat_desks = []
                if hasattr(self.handler, "element_finder"):
                    seat_desks = self.handler.element_finder.find_elements("seat_desk")

                if not seat_desks:
                    self.logger.warning("No seat desks found after expansion")
                    return False

                old_slots = {k: v.copy() for k, v in self.seats.items()}
                desk_mappings = self.map_desks_to_indices(seat_desks)
                pending_inspections = []
                observed_seats_data = {}

                for desk_idx, desk in desk_mappings:
                    left_seat_num = desk_idx * 2 + 1
                    right_seat_num = desk_idx * 2 + 2

                    left_info = self._extract_seat_info(desk, "left", left_seat_num)
                    right_info = self._extract_seat_info(desk, "right", right_seat_num)

                    observed_seats_data[left_seat_num] = (desk, "left", left_info)
                    observed_seats_data[right_seat_num] = (desk, "right", right_info)

                for seat_num, (desk, side, info) in observed_seats_data.items():
                    old_slot = self.seats[seat_num]
                    if info["occupied"]:
                        if old_slot.occupied and old_slot.username:
                            info["username"] = old_slot.username
                        elif not info.get("username"):
                            pending_inspections.append((seat_num, desk, side))

                for seat_num, desk, side in pending_inspections:
                    username = await self.inspect_occupant(desk, side, seat_num)
                    if username:
                        desk, side, info = observed_seats_data[seat_num]
                        info["username"] = username

                for seat_num, (desk, side, info) in observed_seats_data.items():
                    slot = self.seats[seat_num]
                    slot.occupied = info["occupied"]
                    slot.username = info.get("username")
                    slot.label = info.get("label", "")
                    slot.is_owner = info.get("is_owner", False)

                has_changes, changed_users, seat_info = self._compute_diff(
                    old_slots, self.seats, set(observed_seats_data.keys())
                )

                if has_changes:
                    log_msg = self.format_3row_layout(trigger_source="专注人数背离展开重扫")
                    self.logger.info(log_msg)

                    if changed_users:
                        from ushareiplay.managers.command_manager import CommandManager
                        await CommandManager.instance().notify_focus_count_change(
                            self._last_focus_count, target_focus_count, changed_users=changed_users, seat_info=seat_info
                        )

                self._last_focus_count = target_focus_count
                return has_changes

            except Exception as e:
                self.logger.error(f"Error during expand_rescan_and_collapse: {traceback.format_exc()}")
                return False
            finally:
                try:
                    await self.seat_ui.collapse_seats()
                except Exception as e:
                    self.logger.error(f"Failed to collapse seats after rescan: {e}")
                self.release_ui_lock("seat_expansion")
