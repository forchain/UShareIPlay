"""统一配置视图（ADR-0012）。

配置读取此前散落在八种调用形态里：调用方得自己猜手上这份映射到底是根配置
（`config.yaml`）还是某个应用段（`soul` / `qq_music`），于是出现了
`config["elements"]`、`config.get("soul", {}).get("elements")` 这类形状试探，
以及两处永远取不到值的死分支。

本模块给出唯一入口：

- `Locator` —— 选择器值对象。XPath 与 resource-id 的判定、Appium 定位元组、
  绝对/相对 XPath、节点匹配，全部只在这里实现一次。
- `ConfigSectionView` —— 一个应用段（`soul` / `qq_music`）的类型化视图。
- `ConfigView` —— 根配置的类型化视图，按段取子视图。

视图**包裹**底层映射而不复制它：热重载原地改写底层映射，视图实例身份不变，
长生命周期的管理器不需要重新接线（见 `ConfigView.reload`）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from appium.webdriver.common.appiumby import AppiumBy


class ConfigError(Exception):
    """配置读取失败的基类。"""


class MissingConfigSection(ConfigError):
    """请求的配置段不存在。"""

    def __init__(self, section: str):
        super().__init__(f"缺少配置段: {section}")
        self.section = section


class MissingConfigKey(ConfigError):
    """配置段里缺少必需的键。"""

    def __init__(self, section: str, key: str):
        super().__init__(f"配置段 {section} 缺少必需的键: {key}")
        self.section = section
        self.key = key


class MissingElementKey(ConfigError):
    """配置段里缺少 UI 元素选择器。"""

    def __init__(self, section: str, key: str):
        super().__init__(f"配置段 {section} 缺少 UI 元素选择器: {key}")
        self.section = section
        self.key = key


#: 启动期必须存在的元素选择器。缺任何一项都在组合根直接失败，
#: 而不是等到运行期操作 UI 时才炸（见 `AppController` 的启动校验）。
REQUIRED_ELEMENTS: Mapping[str, tuple[str, ...]] = {
    "soul": (
        "message_content",
        "message_list",
        "input_box",
        "button_send",
        "message_reply_view",
        "message_reply_content",
        # 座位面板：这些选择器删掉了硬编码兜底，缺任何一项都会静默观察不到座位。
        "seat_desk",
        "left_seat",
        "right_seat",
        "left_state",
        "right_state",
        "left_label",
        "right_label",
        "left_default_name",
        "right_default_name",
        "left_avatar",
        "right_avatar",
        "left_rank",
        "right_rank",
    ),
    "qq_music": ("search_entry",),
}


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


class ConfigSectionView:
    """一个配置段的类型化视图（``soul`` / ``qq_music``）。

    只提供具名方法，不提供 ``view[...]`` 与 ``view.get(...)`` —— 视图不是字典，
    取值一律走 `.value` / `.require` / `.element`，让「取的是哪一段」在代码里
    一眼可见。
    """

    def __init__(self, name: str, data: MutableMapping[str, Any]):
        self._name = name
        self._data = data
        self._sections: dict[str, ConfigSectionView] = {}

    @property
    def name(self) -> str:
        """段名（``soul`` / ``qq_music`` / 嵌套段名）。"""
        return self._name

    @property
    def data(self) -> Mapping[str, Any]:
        """底层映射（只读用途；改动请走 `ConfigView.reload`）。"""
        return self._data

    def element(self, key: str) -> Locator:
        """必需的元素选择器；缺失即抛 `MissingElementKey`。"""
        locator = self.maybe_element(key)
        if locator is None:
            raise MissingElementKey(self._name, key)
        return locator

    def maybe_element(self, key: str) -> Optional[Locator]:
        """可选的元素选择器；缺失返回 None。"""
        elements = self._data.get("elements")
        if not isinstance(elements, Mapping):
            return None
        value = elements.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        return Locator.from_value(value)

    def value(self, key: str, default: Any = None) -> Any:
        """段内参数；缺失返回 default。"""
        return self._data.get(key, default)

    def require(self, key: str) -> Any:
        """段内必需参数；缺失抛 `MissingConfigKey`。"""
        if key not in self._data:
            raise MissingConfigKey(self._name, key)
        return self._data[key]

    def section(self, key: str) -> "ConfigSectionView":
        """段内的嵌套子段视图；同一子段名恒返回同一实例。"""
        nested = self._data.get(key)
        if not isinstance(nested, Mapping):
            raise MissingConfigKey(self._name, key)
        return self._cached_section(key, nested)

    def maybe_section(self, key: str) -> Optional["ConfigSectionView"]:
        """可选的嵌套子段视图；缺失返回 None。"""
        nested = self._data.get(key)
        if not isinstance(nested, Mapping):
            return None
        return self._cached_section(key, nested)

    def _cached_section(
        self, key: str, nested: Mapping[str, Any]
    ) -> "ConfigSectionView":
        view = self._sections.get(key)
        if view is None:
            view = ConfigSectionView(f"{self._name}.{key}", nested)
            self._sections[key] = view
        return view

    def _reload(self, new_data: Mapping[str, Any]) -> None:
        """原地刷新本视图与已发出的嵌套视图（对象身份不变）。"""
        snapshot = dict(new_data)
        for key in list(self._sections):
            view = self._sections[key]
            nested = new_data.get(key)
            if isinstance(nested, Mapping):
                view._reload(nested)
                snapshot[key] = view._data
            else:
                del self._sections[key]
                view._data.clear()
        self._data.clear()
        self._data.update(snapshot)

    def __repr__(self) -> str:
        return f"<ConfigSectionView {self._name}>"


class ConfigView:
    """根配置的类型化视图。

    包裹底层根映射而不复制它：`reload` 原地改写底层映射，因此根映射本身、
    本视图、以及已发出的段视图实例，身份在热重载前后都保持不变。
    """

    def __init__(self, data: MutableMapping[str, Any]):
        self._data = data
        self._sections: dict[str, ConfigSectionView] = {}

    @property
    def data(self) -> Mapping[str, Any]:
        """底层根映射。"""
        return self._data

    @property
    def soul(self) -> ConfigSectionView:
        """Soul App 段视图。"""
        return self.section("soul")

    @property
    def music(self) -> ConfigSectionView:
        """QQ 音乐段视图。"""
        return self.section("qq_music")

    def section(self, name: str) -> ConfigSectionView:
        """顶层配置段视图；同一段名恒返回同一实例。"""
        view = self._sections.get(name)
        if view is None:
            raw = self._data.get(name)
            if not isinstance(raw, Mapping):
                raise MissingConfigSection(name)
            view = ConfigSectionView(name, raw)
            self._sections[name] = view
        return view

    def maybe_section(self, name: str) -> Optional[ConfigSectionView]:
        """可选的顶层配置段视图；缺失返回 None。"""
        raw = self._data.get(name)
        if not isinstance(raw, Mapping):
            return None
        view = self._sections.get(name)
        if view is None:
            view = ConfigSectionView(name, raw)
            self._sections[name] = view
        return view

    def value(self, key: str, default: Any = None) -> Any:
        """根级参数；缺失返回 default。"""
        return self._data.get(key, default)

    def require(self, key: str) -> Any:
        """根级必需参数；缺失抛 `MissingConfigKey`。"""
        if key not in self._data:
            raise MissingConfigKey("root", key)
        return self._data[key]

    @property
    def command_entries(self) -> list:
        """根级命令表（``commands``）。"""
        entries = self._data.get("commands")
        return list(entries) if isinstance(entries, list) else []

    def validate_required_elements(self) -> None:
        """校验启动期必需的元素选择器；缺项直接抛 `MissingElementKey`。"""
        for section_name, keys in REQUIRED_ELEMENTS.items():
            section = self.section(section_name)
            for key in keys:
                section.element(key)

    def reload(self, new_mapping: Mapping[str, Any]) -> None:
        """原地热重载。

        底层根映射、已发出的段视图与嵌套段视图都在原地改写（对象身份不变），因此
        长生命周期的持有者（Handler / Manager 单例）不需要重新接线就能看到新配置。
        新映射里不存在的段会被移除，对应旧视图清空，不再端着过期配置。
        """
        snapshot = dict(new_mapping)
        for name in list(self._sections):
            view = self._sections[name]
            new_section = new_mapping.get(name)
            if isinstance(new_section, Mapping):
                view._reload(new_section)
                snapshot[name] = view._data
            else:
                del self._sections[name]
                view._data.clear()
        self._data.clear()
        self._data.update(snapshot)

    def __repr__(self) -> str:
        return f"<ConfigView sections={sorted(self._sections)}>"
