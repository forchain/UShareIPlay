from typing import Optional

from ushareiplay.modules.room.ports import LuckPackDriverPort


class InMemoryLuckPackDriver(LuckPackDriverPort):
    """福袋 UI 端口的内存替身，用于验证 LuckPackService 的编排决策。"""

    def __init__(
        self,
        *,
        drawer_opens: bool = True,
        tab_text: Optional[str] = "礼物福袋 (2个)",
        list_ready: bool = True,
        packs: Optional[list[tuple[int, str]]] = None,
        countdown: int = 0,
        countdown_sync_result: Optional[bool] = None,
        use_pack_ready: bool = True,
        heat_entry_opens: bool = True,
        lucky_bag_tab_ready: bool = True,
        lucky_bag_tab_clicks: bool = True,
        heat_sequence: Optional[list[int]] = None,
        tiers: Optional[list[int]] = None,
        auto_open_result: Optional[dict] = None,
    ):
        self.drawer_opens = drawer_opens
        self.tab_text = tab_text
        self.list_ready = list_ready
        self.packs = list(packs) if packs is not None else [(3, "高级福袋"), (1, "初级福袋")]
        self.countdown = countdown
        self.countdown_sync_result = countdown_sync_result
        self.use_pack_ready = use_pack_ready
        self.heat_entry_opens = heat_entry_opens
        self.lucky_bag_tab_ready = lucky_bag_tab_ready
        self.lucky_bag_tab_clicks = lucky_bag_tab_clicks
        self._heat_values = list(heat_sequence) if heat_sequence is not None else [500, 200]
        self._heat_index = 0
        self.tiers = list(tiers) if tiers is not None else [100, 300]
        self.auto_open_result = auto_open_result if auto_open_result is not None else {
            "item": "初级福袋",
            "message": "Successfully opened luck pack 初级福袋",
        }

        self.drawer_closed_count = 0
        self.exchange_closed_count = 0
        self.use_pack_clicks = 0
        self.clicked_levels: list[int] = []
        self.redeemed_costs: list[int] = []
        self.auto_open_calls: list[tuple[Optional[int], bool]] = []

    def open_pack_drawer(self) -> bool:
        return self.drawer_opens

    def wait_pack_tab(self) -> Optional[str]:
        return self.tab_text

    def wait_pack_list(self) -> bool:
        return self.list_ready

    def close_pack_drawer(self) -> bool:
        self.drawer_closed_count += 1
        return True

    def scan_packs(self) -> list[tuple[int, str]]:
        return list(self.packs)

    def locate_pack(self, level: Optional[int]) -> Optional[int]:
        if not self.packs:
            return None
        if level is None:
            return min(lvl for lvl, _ in self.packs)
        for lvl, _ in self.packs:
            if lvl == level:
                return lvl
        return None

    def sync_countdown(self, target: int) -> Optional[bool]:
        if self.countdown_sync_result is not None:
            return self.countdown_sync_result
        if self.countdown == target:
            return False
        self.countdown = target
        return True

    def click_pack(self, level: int) -> bool:
        self.clicked_levels.append(level)
        return any(lvl == level for lvl, _ in self.packs)

    def wait_use_pack_clickable(self) -> bool:
        return self.use_pack_ready

    def click_use_pack(self) -> None:
        self.use_pack_clicks += 1

    def open_heat_exchange_entry(self) -> bool:
        return self.heat_entry_opens

    def wait_lucky_bag_tab(self) -> bool:
        return self.lucky_bag_tab_ready

    def click_lucky_bag_tab(self) -> bool:
        return self.lucky_bag_tab_clicks

    def wait_for_heat(self, below: Optional[int] = None) -> Optional[int]:
        if not self._heat_values or self._heat_index >= len(self._heat_values):
            return None
        val = self._heat_values[self._heat_index]
        if below is not None and val >= below:
            return None
        self._heat_index += 1
        return val

    def redeem_highest_affordable(self, current_heat: int) -> Optional[int]:
        affordable = [cost for cost in self.tiers if cost <= current_heat]
        if not affordable:
            return None
        chosen = max(affordable)
        self.redeemed_costs.append(chosen)
        return chosen

    def exit_exchange_window(self) -> None:
        self.exchange_closed_count += 1

    def auto_open_luck_pack(self, user_count: Optional[int], auto_mode: bool) -> dict:
        self.auto_open_calls.append((user_count, auto_mode))
        return dict(self.auto_open_result)
