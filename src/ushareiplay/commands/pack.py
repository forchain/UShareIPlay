import os
import re
import time
import traceback

from ushareiplay.core.base_command import BaseCommand

MAX_REDEMPTIONS = 50
HEAT_WAIT_SECONDS = 5.0
HEAT_POLL_SECONDS = 0.3
ENTRY_WAIT_SECONDS = 10
DRAWER_WAIT_SECONDS = 10
CLOSE_WAIT_SECONDS = 3
COUNTDOWN_WAIT_SECONDS = 3
PACK_SCAN_MAX = 8
RENDER_WAIT_SECONDS = 1.0
RENDER_POLL_SECONDS = 0.1

PACK_USAGE = '用法: :pack [list|open [level] [countdown]|redeem]'
OPEN_USAGE = '用法: :pack open [level] [countdown]（level 取 1~5，countdown 取 0/1/3/5/10）'

#: 阶段文案 → 福袋等级：「第一阶段奖励」即 1 级福袋。
_PHASE_PATTERN = re.compile(r'第([一二三四五])阶段')
_PHASE_LEVELS = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}

#: 倒计时选项：0 表示即刻抢，其余是分钟数。
COUNTDOWN_OPTIONS = {0: '即刻抢', 1: '1分钟', 3: '3分钟', 5: '5分钟', 10: '10分钟'}

_HEAT_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*([万wW])?')


def _parse_heat(text):
    """Extract the first heat number; tolerate `万`/`w` units and thousands separators."""
    match = _HEAT_PATTERN.search((text or '').replace(',', ''))
    if not match:
        return None
    value = float(match.group(1))
    return int(value * 10000) if match.group(2) else int(value)


def _parse_pack_level(text):
    """从「第X阶段奖励」里读出福袋等级；不是阶段文案返回 None。"""
    match = _PHASE_PATTERN.search(text or '')
    return _PHASE_LEVELS[match.group(1)] if match else None


def _parse_countdown(text):
    """从「即刻抢 | 所有人」/「3分钟 | 所有人」里读出倒计时分钟数（即刻抢 = 0）。"""
    text = (text or '').strip()
    if '即刻抢' in text:
        return 0
    match = re.search(r'(\d+)\s*分钟', text)
    return int(match.group(1)) if match else None


class PackCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to open luck pack'

    def __init__(self, controller):
        super().__init__(controller)
        self.auto_mode = False
        self.previous_count = 0  # Track previous user count

    async def do_process(self, message_info, parameters):
        """Process pack command to list/open luck packs or redeem heat points"""
        self.auto_mode = False  # Manual mode
        subcommand = parameters[0].lower() if parameters else ''
        if subcommand == 'redeem':
            if len(parameters) > 1:
                return {'message': PACK_USAGE}
            return self.redeem_heat()
        if subcommand == 'list':
            if len(parameters) > 1:
                return {'message': PACK_USAGE}
            return self.list_packs()
        if subcommand == 'open':
            return self.open_pack(parameters[1:])
        if subcommand:
            return {'message': f'未知子命令，{PACK_USAGE}'}
        return self.list_packs()

    def update(self):
        """Check room count and auto open pack if needed"""
        try:
            # 从 InfoManager 获取在线人数
            from ushareiplay.managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            count = info_manager.user_count

            if count is None:
                return

            # Only check if count has changed
            if count != self.previous_count:
                self.previous_count = count  # Update previous count
                if count > 5:
                    self.auto_mode = True  # Auto mode
                    self.open_luck_pack(user_count=count)  # Pass user count as parameter

        except Exception as e:
            self.handler.log_error(f"Error in pack update: {traceback.format_exc()}")

    def list_packs(self):
        """打开福袋抽屉，扫描出当前拥有的福袋列表。"""
        if not self._open_pack_drawer():
            return {'error': '未找到福袋入口'}
        try:
            if not self._wait_pack_list():
                return {'error': '福袋抽屉未打开'}
            self.handler.logger.info("已打开福袋抽屉")
            packs = self._scan_packs()
        except Exception:
            self.handler.log_error(f"Error listing packs: {traceback.format_exc()}")
            return {'error': 'Failed to list luck packs'}
        finally:
            # 抽屉必须收干净：留在屏幕上会挡住后面的操作。
            self._close_pack_drawer()
        if not packs:
            return {'message': '当前没有福袋'}
        return {'message': self._format_packs(packs)}

    def open_pack(self, parameters):
        """开启福袋。参数：[level] [countdown]；level 省略时选等级最小的福袋。"""
        level, countdown, error = self._parse_open_args(parameters)
        if error:
            return {'message': error}
        if not self._open_pack_drawer():
            return {'error': '未找到福袋入口'}
        used = False
        try:
            if not self._wait_pack_list():
                return {'error': '福袋抽屉未打开'}
            self.handler.logger.info("已打开福袋抽屉")
            # 先确认福袋存在再改倒计时：倒计时是房间级的持久设置，失败路径不能留下副作用。
            target = self._locate_pack(level)
            if target is None:
                return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            changed = self._sync_countdown(countdown)
            if changed is None:
                return {'error': '倒计时设置失败'}
            if changed:  # 改完倒计时抽屉会重绘，条目要重新定位
                if not self._wait_pack_list():
                    return {'error': '福袋抽屉未打开'}
                target = self._locate_pack(level)
                if target is None:
                    return {'error': f'未找到{level}级福袋' if level else '未找到可用的福袋'}
            target[2].click()
            # 使用按钮在选中福袋之前是灰的：等不到可点的「使用」就是没选中。
            use = self.handler.element_finder.wait_for_element_clickable('use_pack')
            if not use:
                return {'error': '福袋未选中，使用按钮不可用'}
            if os.getenv("VERIFY_ONLY_PACK") == "1":
                self.handler.logger.info(f"[VERIFY_ONLY] 已检测到使用按钮可用（目标 {target[0]} 级福袋），按验证要求不点击开启并安全关闭抽屉")
                return {'message': f'[验证成功] 已检测到{target[0]}级福袋使用按钮，已安全关闭'}
            use.click()
            used = True
            self.handler.logger.info(f'已开启 {target[0]} 级福袋')
            return {'message': f'已开启{target[0]}级福袋'}
        except Exception as e:
            self.handler.log_error(f"Error opening pack: {traceback.format_exc()}")
            return {'error': 'Failed to open luck pack'}
        finally:
            # 开启成功后抽屉会自己落定；其余路径必须手动收掉，不能把抽屉留在屏幕上。
            if not used:
                self._close_pack_drawer()

    def open_luck_pack(self, user_count=None):
        """Open luck pack if available
        Args:
            user_count: Optional[int], current user count in room
        """
        try:
            # Find luck pack button
            luck_pack = self.handler.element_finder.try_find_element('luck_pack', log=False)
            if not luck_pack:
                return {'error': 'No luck pack available'}

            # Check if text contains "奖励"
            pack_text = luck_pack.text
            if "奖励" not in pack_text:
                self.handler.logger.info(f"Luck pack text '{pack_text}' does not contain '奖励'")
                return {'error': 'No luck pack available'}

            # Click luck pack button to show list
            luck_pack.click()
            self.handler.logger.info("Clicked luck pack button")

            # Find and click luck item
            luck_item = self.handler.element_finder.wait_for_element_clickable('luck_item')
            if not luck_item:
                self.handler.logger.error("Failed to find luck item")
                return {'error': 'Failed to find luck item'}

            # In auto mode, check pack level based on user count
            if self.auto_mode and user_count is not None:
                item_text = luck_item.text
                # If less than 10 people, only allow low/medium level packs
                if user_count <= 10 and not (
                        "初级" in item_text or "中级" in item_text or "一级" in item_text or "二级" in item_text):
                    self.handler.logger.info(f"Skipping high level pack with {user_count} users: {item_text}")
                    self.handler.key_actions.press_back()
                    return {'error': 'Skipping high level pack (not enough users)'}

            luck_item.click()
            self.handler.logger.info("Selected luck item")

            # Find and click use pack button
            use_pack = self.handler.element_finder.wait_for_element_clickable('use_pack')
            if not use_pack:
                self.handler.logger.error("Failed to find use pack button")
                return {'error': 'Failed to find use pack button'}

            use_pack.click()
            self.handler.logger.info(f"Used luck pack in {'auto' if self.auto_mode else 'manual'} mode")

            return {
                'item': luck_item.text,
                'message': f"Successfully opened luck pack {luck_item.text}",
            }

        except Exception as e:
            self.handler.log_error(f"Error opening luck pack: {traceback.format_exc()}")
            return {'error': 'Failed to open luck pack'}

    def redeem_heat(self):
        """Redeem heat for luck packs, preferring the highest affordable tier."""
        # 房间顶部的热力进度条是轮播 banner，出现的时机不定，要等它渲染出来
        entry = self.handler.element_finder.wait_for_element(
            'heat_exchange_entry', timeout=ENTRY_WAIT_SECONDS
        )
        if not entry:
            self.handler.logger.warning("Heat exchange entry not found")
            return {'error': '未找到热力兑换入口'}

        opened = False
        try:
            entry.click()
            tab = self._wait_for_lucky_bag_tab()
            if tab is None:
                return {'error': '兑换橱窗未打开，未找到兑换福袋标签页'}
            # 标签页找得到 ⇒ 橱窗确实打开了
            opened = True
            try:
                tab.click()
            except Exception as e:
                self.handler.logger.warning(f"点击兑换福袋标签页失败: {e}")
                return {'error': '切换到兑换福袋标签页失败'}
            self.handler.logger.info("已切换到兑换福袋标签页")

            current_heat = self._wait_for_heat()
            if current_heat is None:
                return {'error': '兑换橱窗已打开，未读取到热力值'}

            redeemed_count = 0
            capped = True
            for _ in range(MAX_REDEMPTIONS):
                # shortcut: page-global XPath; scope it to the exchange container once a real hierarchy dump is available.
                buttons = self.handler.element_finder.find_elements('heat_exchange_buttons')
                affordable = {}
                for btn in buttons:
                    cost = _parse_heat(self.handler.element_finder.get_element_text(btn))
                    if cost is not None and cost <= current_heat:
                        affordable[cost] = btn
                if not affordable:
                    capped = False
                    break

                target_btn = affordable[max(affordable)]
                target_btn.click()
                redeemed_count += 1

                next_heat = self._wait_for_heat(below=current_heat)
                if next_heat is None:
                    self.handler.logger.warning(
                        f"Heat points did not decrease after redemption ({current_heat}), aborting loop"
                    )
                    capped = False
                    break
                current_heat = next_heat

            if capped:
                self.handler.logger.warning(
                    f"Reached redemption cap of {MAX_REDEMPTIONS}, stopping"
                )
            self.handler.logger.info(
                f"Redeemed {redeemed_count} luck packs, remaining heat {current_heat}"
            )
            message = f'成功兑换 {redeemed_count} 个福袋，剩余热力值: {current_heat}'
            if capped:
                message += f'（已达单次上限 {MAX_REDEMPTIONS}）'
            return {'message': message}
        except Exception as e:
            self.handler.log_error(f"Error redeeming heat: {traceback.format_exc()}")
            return {'error': 'Failed to redeem heat'}
        finally:
            # 只有确认橱窗打开了才关窗；否则这次返回可能把机器人踢出派对房间
            if opened:
                self._exit_exchange_window()

    def _wait_for_lucky_bag_tab(self):
        """等「兑换福袋」标签页渲染出来。

        兑换橱窗默认停在「兑换流量卡」，福袋档位按钮不渲染；
        不切页就会把流量卡的价格当成福袋档位点下去。橱窗是 WebView，
        入口点击后要等它把标签页画出来。

        Returns:
            标签页元素；橱窗没打开时返回 None。
        """
        tab = self.handler.element_finder.wait_for_element('heat_exchange_tab', timeout=10)
        if not tab:
            self.handler.logger.warning("兑换福袋标签页未找到")
        return tab

    def _read_remaining_heat(self):
        heat_elem = self.handler.element_finder.try_find_element('heat_remaining_value', log=False)
        if not heat_elem:
            return None
        # 余额节点会被 App 周期性重建，直接取 .text 会抛 StaleElementReferenceException；
        # get_element_text 吞掉异常并返回空串，_parse_heat 返回 None，由 _wait_for_heat 重试。
        return _parse_heat(self.handler.element_finder.get_element_text(heat_elem))

    def _wait_for_heat(self, below=None):
        """Poll until the heat value parses (and, if given, drops below `below`)."""
        deadline = time.monotonic() + HEAT_WAIT_SECONDS
        while True:
            current = self._read_remaining_heat()
            if current is not None and (below is None or current < below):
                return current
            if time.monotonic() >= deadline:
                return None
            time.sleep(HEAT_POLL_SECONDS)

    def _exit_exchange_window(self):
        """Exit exchange window via back button or key press fallback"""
        try:
            back_btn = self.handler.element_finder.try_find_element('heat_exchange_back', log=False)
            if back_btn:
                back_btn.click()
                return
        except Exception as e:
            self.handler.logger.warning(f"Failed to click heat_exchange_back: {e}")
        try:
            self.handler.key_actions.press_back()
        except Exception as e:
            self.handler.logger.warning(f"Failed to press back key: {e}")

    # --- 福袋抽屉 ---

    def _open_pack_drawer(self):
        """点开福袋抽屉；入口不在或点不开返回 False。"""
        entry = self.handler.element_finder.wait_for_element(
            'pack_entry', timeout=ENTRY_WAIT_SECONDS
        )
        if not entry:
            self.handler.logger.warning("未找到福袋入口")
            return False
        try:
            entry.click()
        except Exception as e:
            self.handler.logger.warning(f"点击福袋入口失败: {e}")
            return False
        return True

    def _wait_pack_list(self):
        """等福袋列表渲染出来；抽屉没打开返回 None。"""
        drawer = self.handler.element_finder.wait_for_element(
            'pack_list', timeout=DRAWER_WAIT_SECONDS
        )
        if not drawer:
            self.handler.logger.warning("福袋抽屉未打开")
        return drawer

    def _close_pack_drawer(self):
        """点抓手上沿的遮罩区关闭福袋抽屉；没关掉就按返回兜底。"""
        finder = self.handler.element_finder
        handle = finder.wait_for_element('pack_drawer_handle', timeout=CLOSE_WAIT_SECONDS)
        if handle:
            self.handler.gesture_handler.click_element_at(
                handle, x_ratio=0.5, y_ratio=0, y_offset=-200
            )
        # 手势送达不等于抽屉关掉：以列表消失为准，否则抽屉会挡着后面的操作。
        closed = finder.wait_for_element_disappear('pack_list', timeout=CLOSE_WAIT_SECONDS)
        if not closed:
            self.handler.key_actions.press_back()
            closed = not finder.try_find_element('pack_list', log=False)
        if closed:
            self.handler.logger.info("已关闭福袋抽屉")
        else:
            self.handler.logger.warning("福袋抽屉未能关闭")
        return closed

    def _visible_packs(self):
        """当前可见的福袋条目：(等级, 名称, 阶段文案元素, 元素 y 坐标)。

        列表元素每次都重新取：滑动后 RecyclerView 的节点可能被 App 重建，
        攥着旧引用只会读到空列表。
        """
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
            level = _parse_pack_level(finder.get_element_text(content))
            if level is None:
                continue
            try:
                y = content.location['y']
            except Exception:
                y = -1
            # shortcut: 名称与阶段按列表出现顺序配对；卡片结构变化导致错位时改为按卡片容器定位。
            packs.append((level, names[index] if index < len(names) else '', content, y))
        return packs

    def _wait_visible_packs(self, changed_from=None):
        """等列表子项渲染出来；给了 changed_from 时等这一屏真的换了。"""
        deadline = time.monotonic() + RENDER_WAIT_SECONDS
        while True:
            packs = self._visible_packs()
            if packs and (changed_from is None or not self._same_screen(changed_from, packs)):
                return packs
            if time.monotonic() >= deadline:
                return packs
            time.sleep(RENDER_POLL_SECONDS)

    @staticmethod
    def _same_screen(previous, current):
        """两屏可见条目完全一致（含位置），说明滑动没有产生位移。"""
        return len(previous) == len(current) and all(
            left[:2] == right[:2] and abs(left[3] - right[3]) <= 2
            for left, right in zip(previous, current)
        )

    def _overlap(self, previous, current, direction, expected_shift):
        """相邻两屏有几条是同一件福袋。

        同档位福袋文案完全一样，只靠文案对齐会把新条目当成旧条目；
        用滑动位移把上一屏的坐标换算过来，才能对上身份。
        """
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

    def _scan_packs(self):
        """滑动扫描福袋列表（上下两个方向都扫），返回 [(等级, 名称)]。

        列表倒序（等级从大到小），抽屉可能停在中间：只朝一个方向扫会漏掉
        视口之外的福袋，所以两个方向都要扫。
        """
        self._sweep_packs('up')  # 先滑到顶部，向下扫一遍就是完整列表
        return [(level, name) for level, name, _element, _y in self._sweep_packs('down')]

    def _sweep_packs(self, direction, target_level=None):
        """朝一个方向扫福袋列表，返回 [(等级, 名称, 元素, y)]。

        到底的判据是「滑动后可见条目没有位移」：同档位福袋文案完全一样，
        拿文案当签名会把连续两屏当成没滑动，提前收工。
        给了 target_level 时，扫到那一档立刻返回（元素此刻在屏上，可以直接点）。
        """
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
            self.handler.logger.warning(
                f"福袋列表扫描达到 {PACK_SCAN_MAX} 屏上限，结果可能不完整"
            )
        return collected

    def _swipe_pack_list(self, direction='down'):
        """在福袋列表里滑动一屏，返回滑动距离（滑不了返回 0）。

        direction='down' 露出列表更靠后的条目，'up' 露出更靠前的条目。
        """
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
            self.handler.logger.warning(f"福袋列表滑动失败: {e}")
            return 0

    def _find_pack(self, level):
        """在列表里定位指定等级的福袋条目；上下两个方向都扫。"""
        for direction in ('up', 'down'):
            found = self._sweep_packs(direction, level)
            if found and found[-1][0] == level:
                return found[-1]
        return None

    def _smallest_pack(self):
        """可见条目里等级最小的那个（列表倒序，最小等级在末尾）。"""
        packs = self._visible_packs()
        if not packs:
            return None
        return min(packs, key=lambda pack: pack[0])

    def _locate_pack(self, level):
        """定位福袋条目；level 为 None 时滑到底选等级最小的那个。"""
        if level is not None:
            return self._find_pack(level)
        self._sweep_packs('down')
        return self._smallest_pack()

    def _format_packs(self, packs):
        """把扫描结果渲染成一行可读文案。"""
        counts = {}
        names = {}
        for level, name in packs:
            counts[level] = counts.get(level, 0) + 1
            names.setdefault(level, name)
        parts = []
        for level in sorted(counts, reverse=True):
            name = names[level]
            suffix = f'×{counts[level]}' if counts[level] > 1 else ''
            parts.append(f'{name}（{level}级）{suffix}' if name else f'{level}级福袋{suffix}')
        return f'福袋列表（共{len(packs)}个）：' + '、'.join(parts)

    def _parse_open_args(self, parameters):
        """解析 :pack open 的参数：level（1~5，可省略）、countdown（0/1/3/5/10，默认即刻抢）。"""
        if len(parameters) > 2:
            return None, None, OPEN_USAGE
        level = None
        countdown = 0
        if parameters:
            level, error = self.coerce_int(parameters[0], 1, 5)
            if error:
                return None, None, OPEN_USAGE
        if len(parameters) > 1:
            countdown, error = self.coerce_int(parameters[1])
            if error or countdown not in COUNTDOWN_OPTIONS:
                return None, None, OPEN_USAGE
        return level, countdown, None

    # --- 倒计时 ---

    def _read_countdown(self):
        """当前倒计时（分钟；即刻抢 = 0）；读不到返回 None。"""
        # 列表容器出现时倒计时行可能还没渲染，一次性查询会误判成「不匹配」。
        element = self.handler.element_finder.wait_for_element(
            'pack_countdown_text', timeout=COUNTDOWN_WAIT_SECONDS
        )
        if not element:
            return None
        return _parse_countdown(self.handler.element_finder.get_element_text(element))

    def _sync_countdown(self, target):
        """把倒计时调成目标值。

        返回 None 表示设置失败，否则返回是否真的改动了设置（已经匹配就不动）。
        """
        current = self._read_countdown()
        if current == target:
            return False
        finder = self.handler.element_finder
        try:
            setting = finder.wait_for_element('pack_countdown_entry')
            if not setting:
                self.handler.logger.warning("未找到倒计时设置入口")
                return None
            setting.click()
            item = finder.wait_for_element('pack_countdown_item')
            if not item:
                self.handler.logger.warning("未找到倒计时设置项")
                return None
            item.click()
            option = self._find_countdown_option(target)
            if not option:
                self.handler.logger.warning(f"未找到倒计时选项 {COUNTDOWN_OPTIONS[target]}")
                return None
            option.click()
            confirm = finder.wait_for_element('pack_countdown_confirm')
            if not confirm:
                self.handler.logger.warning("未找到倒计时确认按钮")
                return None
            confirm.click()
        except Exception as e:
            self.handler.logger.warning(f"倒计时设置失败: {e}")
            return None
        self.handler.logger.info(f"倒计时已设置为 {COUNTDOWN_OPTIONS[target]}")
        return True

    def _find_countdown_option(self, target):
        """等倒计时选项渲染出来，找到目标文案。"""
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
