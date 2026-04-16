"""
Samsung OneUI：系统「防误触 / Accidental touch protection」全屏遮罩。

检测到 `locker_img_view` 后，从锁图标中心向上拖动到屏幕高度约 10% 处松开以解除。
"""

__event__ = "AccidentalTouchLockerEvent"
__elements__ = ["accidental_touch_locker"]

import time

from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.base_event import BaseEvent

LOCKER_RESOURCE_ID = "com.android.systemui:id/locker_img_view"


class AccidentalTouchLockerEvent(BaseEvent):
    async def handle(self, key: str, element_wrapper):
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                element = self.handler.wait_for_element(
                    AppiumBy.ID, LOCKER_RESOURCE_ID, timeout=3
                )
                if not element:
                    self.logger.warning(
                        "accidental_touch_locker: element in page_source but not found live"
                    )
                    return True

                loc = element.location
                size = element.size
                start_x = int(loc["x"] + size["width"] / 2)
                start_y = int(loc["y"] + size["height"] / 2)

                window = self.handler.driver.get_window_size()
                screen_h = int(window.get("height", 0))
                screen_w = int(window.get("width", 0))
                end_y = max(0, int(screen_h * 0.10))

                # 若锁已在很靠上，仍保证有一段向上的位移（至少约 5% 屏高）
                min_delta = max(20, int(screen_h * 0.05))
                if start_y - end_y < min_delta:
                    end_y = max(0, start_y - min_delta)

                self.logger.info(
                    "accidental_touch_locker: swipe attempt %s/%s "
                    "from (%s,%s) to (%s,%s) screen=%sx%s",
                    attempt,
                    max_attempts,
                    start_x,
                    start_y,
                    start_x,
                    end_y,
                    screen_w,
                    screen_h,
                )

                ok = self.handler._perform_swipe(
                    start_x, start_y, start_x, end_y, duration_ms=400
                )
                if not ok:
                    self.logger.warning("accidental_touch_locker: _perform_swipe failed")
                    time.sleep(0.3)
                    continue

                time.sleep(0.35)

                try:
                    el2 = self.handler.driver.find_element(
                        AppiumBy.ID, LOCKER_RESOURCE_ID
                    )
                    if el2.is_displayed():
                        self.logger.warning(
                            "accidental_touch_locker: overlay still visible after swipe"
                        )
                        time.sleep(0.2)
                        continue
                except Exception:
                    pass

                self.logger.info("accidental_touch_locker: dismissed")
                return True

            except Exception as e:
                self.logger.error(
                    "AccidentalTouchLockerEvent attempt %s/%s: %s",
                    attempt,
                    max_attempts,
                    e,
                )
                if attempt < max_attempts:
                    time.sleep(0.3)
                    continue
                return True

        self.logger.warning(
            "accidental_touch_locker: still present after %s attempts; "
            "stopping event chain to avoid mis-clicks",
            max_attempts,
        )
        return True
