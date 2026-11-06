"""
派对房间自动抢福袋事件处理器。

状态机生命周期：
[IDLE]
   │ (检测到 lucky_bag_entry)
   ▼
[COUNTDOWN] (记录倒计时目标时间，默认 10s 非阻塞)
   │ ──(福袋提前消失)──► [IDLE]
   │ (10s 到达 & 福袋仍在 & UI 空闲)
   ▼
[CLAIMING] (点击入口 -> 等待 tvOperation / tvOpenFortuneBag 弹窗按钮 -> 点击领取 -> 自动关闭)
   │ ──(超时未找到按钮)──► [返回键兜底]
   ▼
[CLAIMED] (福袋仍在公屏 ──► 抑制重复点击)
   │ ──(福袋按钮完全消失)──► [IDLE]
"""

__event__ = "LuckyBagEntryEvent"
__elements__ = ["lucky_bag_entry"]

import time
from typing import Callable, Optional

from ushareiplay.core.base_event import BaseEvent


class LuckyBagEntryEvent(BaseEvent):
    """自动抢福袋事件处理器"""

    STATE_IDLE = "IDLE"
    STATE_COUNTDOWN = "COUNTDOWN"
    STATE_CLAIMING = "CLAIMING"
    STATE_CLAIMED = "CLAIMED"

    def __init__(self, handler, runtime=None, *, clock: Optional[Callable[[], float]] = None):
        super().__init__(handler, runtime=runtime)
        self._clock: Callable[[], float] = clock or time.time
        self.state: str = self.STATE_IDLE
        self._countdown_target_time: float = 0.0

    @property
    def _lucky_bag_config(self):
        config = self.handler.config
        return config.maybe_section("lucky_bag") if hasattr(config, "maybe_section") else None

    @property
    def enabled(self) -> bool:
        sec = self._lucky_bag_config
        return bool(sec.value("enabled", True)) if sec else True

    @property
    def countdown_seconds(self) -> float:
        sec = self._lucky_bag_config
        val = sec.value("countdown_seconds", 10.0) if sec else 10.0
        try:
            return max(0.0, float(val))
        except (ValueError, TypeError):
            return 10.0

    @property
    def claim_timeout(self) -> float:
        sec = self._lucky_bag_config
        val = sec.value("claim_timeout", 5.0) if sec else 5.0
        try:
            return max(0.5, float(val))
        except (ValueError, TypeError):
            return 5.0

    def _is_soul_foreground(self) -> bool:
        return (
            self.handler.driver.current_package
            == self.handler.config.require("package_name")
        )

    async def handle(self, key: str, element_wrapper) -> bool:
        """处理检测到 lucky_bag_entry 的页面事件。"""
        if not self.enabled:
            return False

        now = self._clock()

        if self.state == self.STATE_IDLE:
            self.state = self.STATE_COUNTDOWN
            self._countdown_target_time = now + self.countdown_seconds
            self.logger.info(
                "检测到派对福袋，启动 %s 秒安全防封倒计时...",
                self.countdown_seconds,
            )
            return False

        if self.state == self.STATE_COUNTDOWN:
            if now < self._countdown_target_time:
                return False

            if self.is_ui_busy():
                self.logger.debug("福袋倒计时已结束，但 UI 处于忙碌状态，推迟至下一轮处理")
                return False

            if not self._is_soul_foreground():
                self.logger.debug("福袋倒计时已结束，但 Soul 不在前台，推迟至下一轮处理")
                return False

            self.state = self.STATE_CLAIMING
            claimed = await self._claim_lucky_bag()
            self.state = self.STATE_CLAIMED
            return claimed

        if self.state == self.STATE_CLAIMED:
            # 当前福袋已被领取，虽然界面上按钮仍在，严格抑制重复点击
            return False

        return False

    async def on_element_absent(self, key: str):
        """当福袋按钮在当前页面消失时触发状态复位。"""
        if key != "lucky_bag_entry":
            return

        if self.state == self.STATE_COUNTDOWN:
            self.logger.info("派对福袋在倒计时期间已消失，取消本次操作并重置状态")
            self.state = self.STATE_IDLE
        elif self.state in (self.STATE_CLAIMED, self.STATE_CLAIMING):
            self.logger.info("派对福袋已从界面完全消失，重置状态以等待下一次福袋")
            self.state = self.STATE_IDLE

    async def _claim_lucky_bag(self) -> bool:
        """执行福袋弹窗点击与领取逻辑。"""
        async with self.ui_session("lucky_bag_claim"):
            entry = self.handler.element_finder.wait_for_element_clickable(
                "lucky_bag_entry", timeout=2
            )
            if not entry:
                self.logger.info("倒计时结束后福袋按钮已不可点击或消失，放弃领取")
                return False

            entry.click()
            self.logger.info("已点击派对福袋入口，等待领取窗口弹出...")

            _key, claim_btn = self.handler.element_finder.wait_for_any_element(
                ["lucky_bag_claim_operation", "lucky_bag_claim_open"],
                timeout=int(self.claim_timeout),
            )

            if claim_btn:
                claim_btn.click()
                self.logger.info("已成功点击福袋领取按钮，窗口自动关闭")
                return True

            self.logger.warning("福袋领取窗口未在时限内出现有效领取按钮")
            if not self._is_soul_foreground():
                self.logger.info("Soul 已不在前台，跳过返回键兜底，避免误操作其它应用")
                return False
            self.logger.info("执行返回键兜底退出福袋弹窗")
            self.handler.key_actions.press_back()
            return False
