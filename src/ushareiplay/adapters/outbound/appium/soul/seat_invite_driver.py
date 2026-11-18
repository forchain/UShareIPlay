"""「邀请入座」底部弹窗的 UI 驱动（Appium 适配器，实现 `SeatInvitePort`）。"""

import asyncio
import logging
import time
from typing import Optional

from ushareiplay.modules.seat.domain import SeatInviteRow
from ushareiplay.modules.seat.ports import SeatInvitePort


class SeatInviteDriver(SeatInvitePort):
    """「邀请入座」底部弹窗的 UI 驱动。

    Args:
        handler: SoulHandler。提供 element_finder / gesture_handler / key_actions。
    """

    ROW_KEY = "seat_invite_row"
    NAME_KEY = "seat_invite_name"
    OPERATION_KEY = "seat_invite_operation"
    CLOSE_KEY = "seat_invite_close"
    PANEL_KEY = "seat_invite_panel"

    INVITABLE_LABELS = ("邀请", "上座")
    SEATED_LABELS = ("已上座",)

    SWIPE_DURATION_MS = 400
    SWIPE_SETTLE_SECONDS = 0.5
    OPEN_POLL_SECONDS = 0.1
    FALLBACK_SCREEN_WIDTH = 1080
    FALLBACK_SCREEN_HEIGHT = 1920

    def __init__(self, handler=None):
        self.handler = handler

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, value):
        self._handler = value
        self._logger = getattr(value, "logger", None)

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self.handler, "logger", None) or logging.getLogger(
                "seat_invite_driver"
            )
        return self._logger

    @property
    def _finder(self):
        return getattr(self.handler, "element_finder", None) if self.handler else None

    def _child_text(self, row, element_key: str) -> str:
        finder = self._finder
        if finder is None or row is None:
            return ""
        try:
            element = finder.find_child_element(row, element_key, log_failure=False)
        except TypeError:
            try:
                element = finder.find_child_element(row, element_key)
            except Exception:
                return ""
        except Exception:
            return ""
        if element is None:
            return ""
        return (getattr(element, "text", "") or "").strip()

    def _child_element(self, row, element_key: str):
        finder = self._finder
        if finder is None or row is None:
            return None
        try:
            return finder.find_child_element(row, element_key, log_failure=False)
        except TypeError:
            try:
                return finder.find_child_element(row, element_key)
            except Exception:
                return None
        except Exception:
            return None

    @classmethod
    def _is_invitable(cls, operation: str) -> bool:
        if any(label in operation for label in cls.SEATED_LABELS):
            return False
        return any(label in operation for label in cls.INVITABLE_LABELS)

    def _read_raw_rows(self) -> list:
        finder = self._finder
        if finder is None:
            return []

        panel = self._panel_element()
        if panel is not None:
            find_child = getattr(finder, "find_child_elements", None)
            if find_child is not None:
                try:
                    return list(find_child(panel, self.ROW_KEY) or [])
                except Exception as e:
                    self.logger.debug(f"在弹窗列表容器里查找用户行失败: {e}")

        try:
            return list(finder.find_elements(self.ROW_KEY) or [])
        except Exception as e:
            self.logger.debug(f"读取邀请入座弹窗的用户行失败: {e}")
            return []

    def _build_rows(self, raw_rows) -> list:
        rows = []
        for row in raw_rows or []:
            name = self._child_text(row, self.NAME_KEY)
            operation_element = self._child_element(row, self.OPERATION_KEY)
            operation = (getattr(operation_element, "text", "") or "").strip()
            rows.append(
                SeatInviteRow(
                    name=name,
                    operation=operation,
                    invitable=self._is_invitable(operation),
                    element=row,
                    operation_element=operation_element,
                )
            )
        return rows

    def read_rows(self) -> list:
        return [row for row in self._build_rows(self._read_raw_rows()) if row.name]

    def is_open(self) -> bool:
        if self.handler is None:
            return False
        try:
            if self.read_rows():
                return True
            return self._panel_element() is not None
        except Exception as e:
            self.logger.debug(f"判定邀请入座弹窗是否打开失败: {e}")
            return False

    def _sheet_on_screen(self) -> bool:
        try:
            if self.read_rows():
                return True
        except Exception:
            pass
        return self._panel_element() is not None

    async def wait_until_open(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            if self.is_open():
                return True
            if time.monotonic() >= deadline:
                self.logger.debug("等待「邀请入座」弹窗打开超时")
                return False
            await asyncio.sleep(self.OPEN_POLL_SECONDS)

    def _panel_element(self):
        finder = self._finder
        if finder is None:
            return None
        try:
            return finder.try_find_element(self.PANEL_KEY, log=False)
        except Exception:
            return None

    def _panel_bounds(self) -> Optional[dict]:
        panel = self._panel_element()
        if not panel:
            return None

        for attr in ("rect", "bounds"):
            value = getattr(panel, attr, None)
            if isinstance(value, dict) and value.get("width") and value.get("height"):
                return value

        location = getattr(panel, "location", None)
        size = getattr(panel, "size", None)
        if isinstance(location, dict) and isinstance(size, dict):
            return {
                "x": location.get("x", 0),
                "y": location.get("y", 0),
                "width": size.get("width", 0),
                "height": size.get("height", 0),
            }
        return None

    def _screen_size(self) -> tuple:
        driver = getattr(self.handler, "driver", None) if self.handler else None
        if driver is not None:
            try:
                window = driver.get_window_size()
                width = int(window.get("width", 0))
                height = int(window.get("height", 0))
                if width > 0 and height > 0:
                    return width, height
            except Exception:
                pass
        return self.FALLBACK_SCREEN_WIDTH, self.FALLBACK_SCREEN_HEIGHT

    def _swipe_area(self) -> tuple:
        bounds = self._panel_bounds()
        if bounds:
            x = bounds.get("x", 0) + bounds.get("width", 0) // 2
            height = bounds.get("height", 0)
            start_y = bounds.get("y", 0) + int(height * 0.75)
            end_y = bounds.get("y", 0) + int(height * 0.25)
            return x, start_y, x, end_y

        width, height = self._screen_size()
        x = width // 2
        return x, int(height * 0.75), x, int(height * 0.45)

    async def _scroll_list(self) -> bool:
        gesture = getattr(self.handler, "gesture_handler", None) if self.handler else None
        if gesture is None or not hasattr(gesture, "swipe"):
            return False

        start_x, start_y, end_x, end_y = self._swipe_area()
        try:
            gesture.swipe(start_x, start_y, end_x, end_y, self.SWIPE_DURATION_MS)
        except Exception as e:
            self.logger.warning(f"滑动邀请入座弹窗的用户列表失败: {e}")
            return False

        await asyncio.sleep(self.SWIPE_SETTLE_SECONDS)
        return True

    async def find_row(self, visible_name: str, max_pages: int = 10) -> Optional[SeatInviteRow]:
        if self.handler is None:
            return None

        seen_signatures = set()
        pages = max(1, max_pages)
        for page in range(pages):
            raw_rows = self._read_raw_rows()
            if not raw_rows:
                return None

            rows = self._build_rows(raw_rows)
            for row in rows:
                if row.name == visible_name:
                    return row

            signature = tuple((row.name or row.operation) for row in rows)
            if signature in seen_signatures:
                self.logger.debug("邀请入座列表翻页后内容未变化，停止翻页")
                return None
            seen_signatures.add(signature)

            if not any(row.name for row in rows):
                self.logger.debug("邀请入座列表这一页还没渲染出昵称，翻页继续找")

            if page == pages - 1:
                break

            if not await self._scroll_list():
                return None

        return None

    def click_invite(self, row: SeatInviteRow) -> bool:
        if row is None or not row.invitable:
            return False

        element = getattr(row, "operation_element", None)
        if element is None:
            return False

        try:
            element.click()
        except Exception as e:
            self.logger.warning(f"点击邀请按钮失败: {e}")
            return False
        return True

    def close(self) -> bool:
        finder = self._finder
        if finder is None:
            return False

        if not self._sheet_on_screen():
            self.logger.debug("没有证据表明「邀请入座」弹窗在屏幕上，不点关闭按钮")
            return False

        try:
            button = finder.try_find_element(self.CLOSE_KEY, log=False)
        except Exception as e:
            self.logger.warning(f"查找邀请入座弹窗的关闭按钮失败: {e}")
            return False

        if not button:
            return False

        try:
            button.click()
        except Exception as e:
            self.logger.warning(f"点击邀请入座弹窗的关闭按钮失败: {e}")
            return False
        return True
