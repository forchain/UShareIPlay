from __future__ import annotations

import traceback
from typing import Optional, Tuple

from lxml import etree
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.remote.webelement import WebElement

from ushareiplay.core.driver_decorator import with_driver_recovery


class GestureHandler:
    def __init__(self, owner):
        self.owner = owner

    def __getattr__(self, name):
        return getattr(self.owner, name)

    @property
    def driver(self):
        return self.owner.driver

    @property
    def config(self):
        return self.owner.config

    @property
    def logger(self):
        return self.owner.logger

    def _clamp_click_coords(self, click_x: int, click_y: int) -> Tuple[int, int]:
        """Clamp tap coordinates to the visible screen bounds."""
        try:
            window = self.driver.get_window_size()
            screen_w = int(window.get("width", 0))
            screen_h = int(window.get("height", 0))
        except Exception:
            screen_w = screen_h = 0

        if screen_w > 0:
            click_x = max(0, min(click_x, screen_w - 1))
        else:
            click_x = max(0, click_x)

        if screen_h > 0:
            click_y = max(0, min(click_y, screen_h - 1))
        elif click_y < 60:
            click_y = 60
        else:
            click_y = max(0, click_y)

        return click_x, click_y

    def _perform_click_at(self, click_x: int, click_y: int, element=None) -> bool:
        """Tap at absolute screen coordinates with UiAutomator2-friendly fallbacks."""
        click_x, click_y = self._clamp_click_coords(click_x, click_y)

        try:
            self.driver.execute_script(
                "mobile: clickGesture", {"x": click_x, "y": click_y}
            )
            return True
        except Exception:
            self.logger.debug(
                "mobile: clickGesture failed, falling back to W3C touch actions"
            )

        try:
            actions = ActionChains(self.driver)
            actions.w3c_actions = ActionBuilder(
                self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, "touch")
            )
            pointer = actions.w3c_actions.pointer_action
            pointer.move_to_location(click_x, click_y)
            pointer.pointer_down()
            pointer.pause(0.1)
            pointer.pointer_up()
            actions.perform()
            return True
        except Exception:
            self.logger.debug("W3C touch click failed, falling back to element.click()")

        if element is not None:
            try:
                element.click()
                return True
            except Exception:
                pass

        return False

    @with_driver_recovery(retry=False, op="write")
    def click_element_at(
            self, element, x_ratio=0.5, y_ratio=0.5, x_offset=0, y_offset=0
    ):
        """Click element at specified position ratio
        Args:
            element: WebElement to click
            x_ratio: float, horizontal position ratio (0.0 to 1.0), default 0.5 for center
            y_ratio: float, vertical position ratio (0.0 to 1.0), default 0.5 for center
        Returns:
            bool: True if click successful, False otherwise
        """
        try:
            if not element:
                return False

            size = element.size
            location = element.location

            click_x = location["x"] + int(x_offset) + int(size["width"] * x_ratio)
            click_y = location["y"] + int(y_offset) + int(size["height"] * y_ratio)
            raw_x, raw_y = click_x, click_y
            click_x, click_y = self._clamp_click_coords(click_x, click_y)
            if (click_x, click_y) != (raw_x, raw_y):
                self.logger.warning(
                    f"Click position clamped from ({raw_x}, {raw_y}) to ({click_x}, {click_y})"
                )

            if not self._perform_click_at(click_x, click_y, element=element):
                self.logger.error(
                    f"All click strategies failed at position ({click_x}, {click_y})"
                )
                return False

            self.logger.debug(f"Clicked element at position ({click_x}, {click_y})")
            return True

        except Exception:
            self.logger.error(f"Error clicking element: {traceback.format_exc()}")
            return False

    def _reversed_if_needed(self, lst: list, direction: str) -> list:
        return list(reversed(lst)) if direction in ("down", "right") else lst

    @with_driver_recovery(retry=False, op="write")
    def _perform_swipe(
            self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> bool:
        """在指定坐标执行一次滑动。

        Args:
            start_x: 起点 X
            start_y: 起点 Y
            end_x: 终点 X
            end_y: 终点 Y
            duration_ms: 按下到抬起的持续时间（毫秒）
        Returns:
            bool: 是否执行成功
        """
        try:
            self.driver.swipe(start_x, start_y, end_x, end_y, duration_ms)
            return True
        except Exception:
            self.logger.error(f"Error performing swipe: {traceback.format_exc()}")
            return False

    def swipe(
            self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300
    ) -> bool:
        """Perform one swipe using the gesture abstraction."""
        return self._perform_swipe(start_x, start_y, end_x, end_y, duration_ms=duration_ms)

    @with_driver_recovery(op="read")
    def scroll_container_until_element(
            self, element_key: str, container_key: str, direction: str = "up", attribute_name: str = None,
            attribute_value: str = None, max_swipes: int = 10
    ) -> Tuple[Optional[str], Optional[WebElement], list[str]]:
        """在指定容器内滚动，直到找到目标元素或无法继续滚动。

        参数：
            element_key: 目标元素在配置中的 key（应为容器的子元素）
            container_key: 容器元素在配置中的 key
            direction: 滚动方向，支持 'up'|'down'|'left'|'right'，默认 'up'（自下向上）
            attribute_name: 要匹配的属性名（支持 | 分隔的多个属性）
            attribute_value: 要匹配的属性值
            max_swipes: 最多滑动次数，默认 10 次

        策略：
            以 'up' 为例：每次从容器可视部分约 80% 处滑动到容器顶部附近（约 10%），滑动后尝试查找子元素；
            若找到则返回 (element_key, element, attribute_values)。若连续滑动后页面不再变化（page_source 无变化），则认为到达边界，返回 (None, None, attribute_values)。

        返回：
            (key, element, attribute_values): 找到目标元素时返回
            (None, None, attribute_values): 未找到目标元素时返回
            attribute_values: 搜索过程中找到的所有目标元素的 attribute 值列表，按元素出现顺序排列
        """
        # 收集所有找到的元素的 attribute 值列表
        attribute_values_list = []
        try:
            def snapshot() -> tuple[str, int]:
                try:
                    page_source = self.driver.page_source or ""
                    return page_source, hash(page_source)
                except Exception:
                    return "", 0

            def target_values(source: str) -> tuple[list[str], bool]:
                selector = (self.config.get("elements") or {}).get(element_key)
                if not source or not selector:
                    return [], False
                root = etree.fromstring(source.encode("utf-8"))
                elements = (
                    root.xpath(selector)
                    if selector.startswith("//")
                    else root.xpath(f"//*[@resource-id='{selector}']")
                )
                attrs = attribute_name.split("|") if attribute_name else ["content-desc", "text"]
                values = []
                matched = False
                for element in elements:
                    element_values = [element.get(attr) for attr in attrs]
                    value = next((item for item in element_values if item and item != "null"), None)
                    if value is not None:
                        values.append(value)
                    if attribute_value is None or attribute_value in element_values:
                        matched = True
                return values, matched

            page_source, prev_hash = snapshot()
            values, matched = target_values(page_source)
            attribute_values_list.extend(values)

            # 获取容器（横滑区等父节点可能不可点击，回退为仅存在即可）
            container = self.owner.element_finder.wait_for_element_clickable(container_key)
            if not container:
                container = self.owner.element_finder.wait_for_element(container_key)
            if not container:
                self.logger.warning(
                    f"scroll_container_until_element: 容器未找到: {container_key}"
                )
                return None, None, attribute_values_list

            def find_visible_target() -> Optional[WebElement]:
                candidates = self.owner.element_finder.find_child_elements(
                    container, element_key
                )
                if attribute_value is None:
                    return candidates[0] if candidates else None

                attrs = (
                    attribute_name.split("|")
                    if attribute_name
                    else ["content-desc", "text"]
                )
                for candidate in candidates:
                    for attr in attrs:
                        value = self.owner.element_finder.try_get_attribute(
                            candidate, attr
                        )
                        if value == attribute_value:
                            return candidate
                return None

            if matched:
                target = find_visible_target()
                if target:
                    return element_key, target, self._reversed_if_needed(attribute_values_list, direction)

            # 方向规范化
            valid_dirs = {"up", "down", "left", "right"}
            if direction not in valid_dirs:
                self.logger.warning(
                    f"scroll_container_until_element: 非法方向 {direction}，使用默认 'up'"
                )
                direction = "up"

            # 预计算容器可视坐标
            loc = container.location
            size = container.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            # 单次滑动的起止点计算（默认 'up'）
            def compute_points(dir_name: str):
                if dir_name == "up":
                    start_x = left + int(width * 0.5)
                    start_y = top + int(height * 0.9)
                    end_x = left + int(width * 0.5)
                    end_y = top + int(height * 0.1)
                    return start_x, start_y, end_x, end_y
                if dir_name == "down":
                    start_x = left + int(width * 0.5)
                    start_y = top + int(height * 0.1)
                    end_x = left + int(width * 0.5)
                    end_y = top + int(height * 0.9)
                    return start_x, start_y, end_x, end_y
                if dir_name == "left":
                    start_x = left + int(width * 0.9)
                    start_y = top + int(height * 0.5)
                    end_x = left + int(width * 0.2)
                    end_y = top + int(height * 0.5)
                    return start_x, start_y, end_x, end_y
                # right
                start_x = left + int(width * 0.1)
                start_y = top + int(height * 0.5)
                end_x = left + int(width * 0.9)
                end_y = top + int(height * 0.5)
                return start_x, start_y, end_x, end_y

            # 开始循环滑动查找
            stable_rounds = 0
            max_stable_rounds = 2  # 连续多次无变化则认为到达边界

            # 查找目标元素的辅助函数
            def find_target_element(source: str) -> Tuple[Optional[str], Optional[WebElement]]:
                """先用 page source 判断命中，再解析对应的可见元素。"""
                values, matched = target_values(source)
                attribute_values_list.extend(values)
                if not matched:
                    return None, None
                target = find_visible_target()
                return (element_key, target) if target else (None, None)

            for _ in range(max_swipes):
                # 计算滑动坐标并执行滑动
                sx, sy, ex, ey = compute_points(direction)
                ok = self._perform_swipe(sx, sy, ex, ey, duration_ms=300)
                if not ok:
                    self.logger.warning(
                        f"scroll_container_until_element: 滑动失败，终止:{element_key}"
                    )
                    return None, None, self._reversed_if_needed(attribute_values_list, direction)

                # 滑动后再试一次（元素可能已进入可视区）
                page_source, cur_hash = snapshot()
                key, element = find_target_element(page_source)
                if element:
                    return key, element, self._reversed_if_needed(attribute_values_list, direction)

                # 判断是否到底/到边（页面无变化）
                if cur_hash == prev_hash:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    prev_hash = cur_hash

                if stable_rounds >= max_stable_rounds:
                    self.logger.warning(
                        f"scroll_container_until_element: 已到达边界，未找到目标元素:{element_key}"
                    )
                    return None, None, self._reversed_if_needed(attribute_values_list, direction)

            self.logger.warning(
                f"scroll_container_until_element: 达到最大滑动次数，未找到目标元素:{element_key}"
            )
            return None, None, self._reversed_if_needed(attribute_values_list, direction)
        except Exception:
            self.logger.error(
                f"scroll_container_until_element error: {traceback.format_exc()}"
            )
            return None, None, self._reversed_if_needed(attribute_values_list, direction)
