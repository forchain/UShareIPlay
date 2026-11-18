"""生产适配器：把 Soul App 福袋抽屉、倒计时与热力兑换的 Appium 操作封装在 LuckPackDriverPort 之后。"""

import logging
import time
import traceback
from typing import Optional

from ushareiplay.modules.room.domain import (
    COUNTDOWN_OPTIONS,
    parse_countdown,
    parse_heat,
    parse_pack_level,
    should_skip_auto_pack,
)
from ushareiplay.modules.room.ports import LuckPackDriverPort

HEAT_WAIT_SECONDS = 5.0
HEAT_POLL_SECONDS = 0.3
ENTRY_WAIT_SECONDS = 10
DRAWER_WAIT_SECONDS = 10
CLOSE_WAIT_SECONDS = 3
COUNTDOWN_WAIT_SECONDS = 3
PACK_SCAN_MAX = 8
RENDER_WAIT_SECONDS = 1.0
RENDER_POLL_SECONDS = 0.1


class SoulLuckPackDriver(LuckPackDriverPort):
    """基于 SoulHandler 的福袋与热力兑换 UI 驱动。"""

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)
        self._last_located_entry = None

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("SoulLuckPackDriver")
        return self._logger

    def open_pack_drawer(self) -> bool:
        entry = self.handler.element_finder.wait_for_element(
            'pack_entry', timeout=ENTRY_WAIT_SECONDS
        )
        if not entry:
            self.logger.warning("未找到福袋入口")
            return False
        try:
            entry.click()
        except Exception as e:
            self.logger.warning(f"点击福袋入口失败: {e}")
            return False
        return True

    def wait_pack_tab(self) -> Optional[str]:
        tab = self.handler.element_finder.wait_for_element(
            'pack_tab', timeout=DRAWER_WAIT_SECONDS
        )
        if not tab:
            self.logger.warning("福袋抽屉未打开")
            return None
        return self.handler.element_finder.get_element_text(tab)

    def wait_pack_list(self) -> bool:
        drawer = self.handler.element_finder.wait_for_element(
            'pack_list', timeout=DRAWER_WAIT_SECONDS
        )
        if not drawer:
            self.logger.warning("未找到福袋列表")
            return False
        return True

    def close_pack_drawer(self) -> bool:
        finder = self.handler.element_finder
        handle = finder.wait_for_element('pack_drawer_handle', timeout=CLOSE_WAIT_SECONDS)
        if handle:
            self.handler.gesture_handler.click_element_at(
                handle, x_ratio=0.5, y_ratio=0, y_offset=-200
            )
        closed = finder.wait_for_element_disappear('pack_list', timeout=CLOSE_WAIT_SECONDS)
        if not closed:
            self.handler.key_actions.press_back()
            closed = not finder.try_find_element('pack_list', log=False)
        if closed:
            self.logger.info("已关闭福袋抽屉")
        else:
            self.logger.warning("福袋抽屉未能关闭")
        return closed

    def _visible_packs(self):
        finder = self.handler.element_finder
        drawer = finder.try_find_element('pack_list', log=False)
        if not drawer:
            return []
        contents = finder.find_child_elements(drawer, 'pack_content')
        names = [
            finder.get_element_text(name)
            for name in finder.find_child_elements(drawer, 'luck_item')
        ]
        packs = []
        for index, content in enumerate(contents):
            level = parse_pack_level(finder.get_element_text(content))
            if level is None:
                continue
            try:
                y = content.location['y']
            except Exception:
                y = -1
            packs.append((level, names[index] if index < len(names) else '', content, y))
        return packs

    def _wait_visible_packs(self, changed_from=None):
        deadline = time.monotonic() + RENDER_WAIT_SECONDS
        while True:
            packs = self._visible_packs()
            if packs and (changed_from is None or not self._same_screen(changed_from, packs)):
                return packs
            if time.monotonic() >= deadline:
                return packs
            time.sleep(RENDER_POLL_SECONDS)

    @staticmethod
    def _same_screen(previous, current) -> bool:
        return len(previous) == len(current) and all(
            left[:2] == right[:2] and abs(left[3] - right[3]) <= 2
            for left, right in zip(previous, current)
        )

    @staticmethod
    def _overlap(previous, current, direction, expected_shift):
        backwards = 1 if direction == 'up' else -1
        moves = [
            right[3] - left[3]
            for left in previous for right in current
            if left[:2] == right[:2] and (right[3] - left[3]) * backwards > 0
        ]
        if not moves:
            return 0
        shift = min(moves, key=lambda move: abs(abs(move) - expected_shift))
        ordered = current if direction == 'down' else list(reversed(current))
        seen = {(level, name, y) for level, name, _element, y in previous}
        for count, (level, name, _element, y) in enumerate(ordered, start=1):
            if (level, name, y - shift) not in seen:
                return count - 1
        return len(ordered)

    def _swipe_pack_list(self, direction: str = 'down') -> int:
        try:
            drawer = self.handler.element_finder.try_find_element('pack_list', log=False)
            if not drawer:
                return 0
            location = drawer.location
            size = drawer.size
            center_x = int(location['x'] + size['width'] / 2)
            top = int(location['y'])
            height = int(size['height'])
            if direction == 'up':
                start_y, end_y = top + int(height * 0.15), top + int(height * 0.85)
            else:
                start_y, end_y = top + int(height * 0.85), top + int(height * 0.15)
            if not self.handler.gesture_handler.swipe(
                center_x, start_y, center_x, end_y, duration_ms=300
            ):
                return 0
            return abs(end_y - start_y)
        except Exception as e:
            self.logger.warning(f"福袋列表滑动失败: {e}")
            return 0

    def _sweep_packs(self, direction: str, target_level: Optional[int] = None):
        collected = []
        previous = None
        expected_shift = 0
        screen = self._wait_visible_packs()
        for _ in range(PACK_SCAN_MAX):
            if not screen:
                break
            if previous is None:
                fresh = screen
            else:
                overlap = self._overlap(previous, screen, direction, expected_shift)
                fresh = screen[overlap:] if direction == 'down' else screen[:len(screen) - overlap]
            for entry in fresh:
                collected.append(entry)
                if entry[0] == target_level:
                    return collected
            previous = screen
            expected_shift = self._swipe_pack_list(direction)
            if not expected_shift:
                break
            screen = self._wait_visible_packs(previous)
            if self._same_screen(previous, screen):
                break
        else:
            self.logger.warning(f"福袋列表扫描达到 {PACK_SCAN_MAX} 屏上限，结果可能不完整")
        return collected

    def scan_packs(self) -> list[tuple[int, str]]:
        self._sweep_packs('up')
        return [(level, name) for level, name, _element, _y in self._sweep_packs('down')]

    def _find_pack(self, level: int):
        for direction in ('up', 'down'):
            found = self._sweep_packs(direction, level)
            if found and found[-1][0] == level:
                return found[-1]
        return None

    def _smallest_pack(self):
        packs = self._visible_packs()
        if not packs:
            return None
        return min(packs, key=lambda pack: pack[0])

    def locate_pack(self, level: Optional[int]) -> Optional[int]:
        self._last_located_entry = None
        if level is not None:
            entry = self._find_pack(level)
        else:
            self._sweep_packs('down')
            entry = self._smallest_pack()
        if entry is None:
            return None
        self._last_located_entry = entry
        return entry[0]

    def click_pack(self, level: int) -> bool:
        entry = self._last_located_entry
        if entry is None or entry[0] != level:
            entry = self._find_pack(level)
        if entry is None:
            return False
        entry[2].click()
        return True

    def _read_countdown(self) -> Optional[int]:
        element = self.handler.element_finder.wait_for_element(
            'pack_countdown_text', timeout=COUNTDOWN_WAIT_SECONDS
        )
        if not element:
            return None
        return parse_countdown(self.handler.element_finder.get_element_text(element))

    def _find_countdown_option(self, target: int):
        finder = self.handler.element_finder
        wanted = COUNTDOWN_OPTIONS[target]
        deadline = time.monotonic() + COUNTDOWN_WAIT_SECONDS
        while True:
            for option in finder.find_elements('pack_countdown_option'):
                if finder.get_element_text(option) == wanted:
                    return option
            if time.monotonic() >= deadline:
                return None
            time.sleep(RENDER_POLL_SECONDS)

    def sync_countdown(self, target: int) -> Optional[bool]:
        current = self._read_countdown()
        if current == target:
            return False
        finder = self.handler.element_finder
        try:
            setting = finder.wait_for_element('pack_countdown_entry')
            if not setting:
                self.logger.warning("未找到倒计时设置入口")
                return None
            setting.click()
            item = finder.wait_for_element('pack_countdown_item')
            if not item:
                self.logger.warning("未找到倒计时设置项")
                return None
            item.click()
            option = self._find_countdown_option(target)
            if not option:
                self.logger.warning(f"未找到倒计时选项 {COUNTDOWN_OPTIONS[target]}")
                return None
            option.click()
            confirm = finder.wait_for_element('pack_countdown_confirm')
            if not confirm:
                self.logger.warning("未找到倒计时确认按钮")
                return None
            confirm.click()
        except Exception as e:
            self.logger.warning(f"倒计时设置失败: {e}")
            return None
        self.logger.info(f"倒计时已设置为 {COUNTDOWN_OPTIONS[target]}")
        return True

    def wait_use_pack_clickable(self) -> bool:
        return bool(self.handler.element_finder.wait_for_element_clickable('use_pack'))

    def click_use_pack(self) -> None:
        use = self.handler.element_finder.wait_for_element_clickable('use_pack')
        if use:
            use.click()

    def open_heat_exchange_entry(self) -> bool:
        entry = self.handler.element_finder.wait_for_element(
            'heat_exchange_entry', timeout=ENTRY_WAIT_SECONDS
        )
        if not entry:
            self.logger.warning("Heat exchange entry not found")
            return False
        entry.click()
        return True

    def wait_lucky_bag_tab(self) -> bool:
        tab = self.handler.element_finder.wait_for_element('heat_exchange_tab', timeout=10)
        if not tab:
            self.logger.warning("兑换福袋标签页未找到")
            return False
        return True

    def click_lucky_bag_tab(self) -> bool:
        tab = self.handler.element_finder.wait_for_element('heat_exchange_tab', timeout=10)
        if not tab:
            return False
        try:
            tab.click()
            return True
        except Exception as e:
            self.logger.warning(f"点击兑换福袋标签页失败: {e}")
            return False

    def _read_remaining_heat(self) -> Optional[int]:
        heat_elem = self.handler.element_finder.try_find_element('heat_remaining_value', log=False)
        if not heat_elem:
            return None
        return parse_heat(self.handler.element_finder.get_element_text(heat_elem))

    def wait_for_heat(self, below: Optional[int] = None) -> Optional[int]:
        deadline = time.monotonic() + HEAT_WAIT_SECONDS
        while True:
            current = self._read_remaining_heat()
            if current is not None and (below is None or current < below):
                return current
            if time.monotonic() >= deadline:
                return None
            time.sleep(HEAT_POLL_SECONDS)

    def redeem_highest_affordable(self, current_heat: int) -> Optional[int]:
        buttons = self.handler.element_finder.find_elements('heat_exchange_buttons')
        affordable = {}
        for btn in buttons:
            cost = parse_heat(self.handler.element_finder.get_element_text(btn))
            if cost is not None and cost <= current_heat:
                affordable[cost] = btn
        if not affordable:
            return None
        best_cost = max(affordable)
        affordable[best_cost].click()
        return best_cost

    def exit_exchange_window(self) -> None:
        try:
            back_btn = self.handler.element_finder.try_find_element('heat_exchange_back', log=False)
            if back_btn:
                back_btn.click()
                return
        except Exception as e:
            self.logger.warning(f"Failed to click heat_exchange_back: {e}")
        try:
            self.handler.key_actions.press_back()
        except Exception as e:
            self.logger.warning(f"Failed to press back key: {e}")

    def auto_open_luck_pack(self, user_count: Optional[int], auto_mode: bool) -> dict:
        try:
            luck_pack = self.handler.element_finder.try_find_element('luck_pack', log=False)
            if not luck_pack:
                return {'error': 'No luck pack available'}

            pack_text = luck_pack.text
            if "奖励" not in pack_text:
                self.logger.info(f"Luck pack text '{pack_text}' does not contain '奖励'")
                return {'error': 'No luck pack available'}

            luck_pack.click()
            self.logger.info("Clicked luck pack button")

            luck_item = self.handler.element_finder.wait_for_element_clickable('luck_item')
            if not luck_item:
                self.logger.error("Failed to find luck item")
                return {'error': 'Failed to find luck item'}

            if auto_mode and should_skip_auto_pack(user_count, luck_item.text):
                self.logger.info(f"Skipping high level pack with {user_count} users: {luck_item.text}")
                self.handler.key_actions.press_back()
                return {'error': 'Skipping high level pack (not enough users)'}

            luck_item.click()
            self.logger.info("Selected luck item")

            use_pack = self.handler.element_finder.wait_for_element_clickable('use_pack')
            if not use_pack:
                self.logger.error("Failed to find use pack button")
                return {'error': 'Failed to find use pack button'}

            use_pack.click()
            self.logger.info(f"Used luck pack in {'auto' if auto_mode else 'manual'} mode")

            return {
                'item': luck_item.text,
                'message': f"Successfully opened luck pack {luck_item.text}",
            }
        except Exception:
            self.logger.error(f"Error opening luck pack: {traceback.format_exc()}")
            return {'error': 'Failed to open luck pack'}
