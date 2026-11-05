import re
import time
import traceback

from ushareiplay.core.base_command import BaseCommand

MAX_REDEMPTIONS = 50
HEAT_WAIT_SECONDS = 5.0
HEAT_POLL_SECONDS = 0.3
ENTRY_WAIT_SECONDS = 10

_HEAT_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*([万wW])?')


def _parse_heat(text):
    """Extract the first heat number; tolerate `万`/`w` units and thousands separators."""
    match = _HEAT_PATTERN.search((text or '').replace(',', ''))
    if not match:
        return None
    value = float(match.group(1))
    return int(value * 10000) if match.group(2) else int(value)


class PackCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = 'Failed to open luck pack'

    def __init__(self, controller):
        super().__init__(controller)
        self.auto_mode = False
        self.previous_count = 0  # Track previous user count

    async def do_process(self, message_info, parameters):
        """Process pack command to open luck pack or redeem heat points"""
        self.auto_mode = False  # Manual mode
        subcommand = parameters[0].lower() if parameters else ''
        if subcommand == 'redeem':
            if len(parameters) > 1:
                return {'message': '用法: :pack [redeem]'}
            return self.redeem_heat()
        if subcommand:
            return {'message': '未知子命令，用法: :pack [redeem]'}
        return self.open_luck_pack()

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
