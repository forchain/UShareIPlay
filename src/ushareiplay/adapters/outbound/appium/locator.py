"""UI 选择器值对象（ADR-0012 / ADR-0013）。

`Locator` 编码的是 selector strategy —— XPath 与 resource-id 的判定、Appium
定位元组、绝对/相对 XPath、节点匹配。这些是技术细节，因此住在 Appium 出站
适配器里，共享内核只暴露配置里的选择器字符串。
"""

from __future__ import annotations

from dataclasses import dataclass

from appium.webdriver.common.appiumby import AppiumBy


@dataclass(frozen=True)
class Locator:
    """UI 选择器值对象。

    `kind` 只有两种取值：

    - ``"xpath"`` —— 选择器以 ``//`` 或 ``./`` 开头，是一条 XPath；
    - ``"id"`` —— 其它一律按 Android resource-id 处理。

    这个判定规则此前在 `element_finder`、`event_manager`、`gesture_handler`、
    `seat_panel_driver` 四处各写了一遍，现在只有这里一份。
    """

    kind: str
    value: str

    @classmethod
    def from_value(cls, value: str) -> "Locator":
        """按选择器字符串建 Locator（``//`` 或 ``./`` 开头算 XPath，其余算 resource-id）。"""
        text = (value or "").strip()
        kind = "xpath" if text.startswith(("//", "./")) else "id"
        return cls(kind=kind, value=text)

    @property
    def appium(self) -> tuple[str, str]:
        """Appium 定位元组 ``(by, value)``。"""
        by = AppiumBy.XPATH if self.kind == "xpath" else AppiumBy.ID
        return (by, self.value)

    @property
    def absolute_xpath(self) -> str:
        """在整页 XML 里定位该元素的 XPath。"""
        if self.kind == "xpath":
            return self.value
        return f"//*[@resource-id='{self.value}']"

    @property
    def relative_xpath(self) -> str:
        """在父节点下定位该子元素的相对 XPath。"""
        if self.kind == "xpath":
            return self.value if self.value.startswith(".") else f".{self.value}"
        return f".//*[@resource-id='{self.value}']"

    def matches(self, node) -> bool:
        """node 是否是本选择器指向的那个元素。

        resource-id 沿用既有语义：裸 id 与带包名前缀的 id 互相认得
        （``gReplyView`` 认得 ``cn.soulapp.android:id/gReplyView``）。
        XPath 则在 node 所属文档里求值，看是否命中 node 自身。
        """
        if self.kind == "id":
            node_id = node.get("resource-id") or ""
            if not node_id:
                return False
            return node_id == self.value or node_id.endswith(f"/{self.value}")

        try:
            tree = node.getroottree()
            path = tree.getpath(node)
            return any(tree.getpath(hit) == path for hit in tree.xpath(self.value))
        except Exception:
            return False
