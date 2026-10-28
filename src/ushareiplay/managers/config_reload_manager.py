"""配置热重载（#469）：把 config.yaml 的新内容热灌进运行中的组件。

流程刻意分成两段：

1. 读盘 + 校验 —— 这一段任何失败都不动活配置（半截的 / 走样的 config.yaml
   绝不能把跑着的机器人变成砖头：ElementFinder 每次查元素都会读配置）；
2. 原地写入 + 重绑元素映射 —— 这一段成功才算热重载完成。

「原地写入」是关键：`ElementFinder`、`EventManager` 等组件缓存的是 handler.config
这一个 dict 对象，把根配置换成新对象，它们会继续用旧选择器。
"""

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from ushareiplay.core.config_loader import ConfigLoader


@dataclass(frozen=True)
class ElementMappingDiff:
    """元素绑定映射的变化。

    Attributes:
        added: 新增的元素 key → 事件模块名
        removed: 消失的元素 key → 事件模块名（重载前）
        remapped: 改绑的元素 key → (旧模块名, 新模块名)
    """

    added: Mapping[str, str] = field(default_factory=dict)
    removed: Mapping[str, str] = field(default_factory=dict)
    remapped: Mapping[str, Tuple[str, str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.remapped)

    def render(self) -> str:
        lines = [f"+ {key} → {module}" for key, module in self.added.items()]
        lines += [f"- {key} → {module}" for key, module in self.removed.items()]
        lines += [
            f"~ {key}: {old} → {new}" for key, (old, new) in self.remapped.items()
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class ReloadReport:
    """一次热重载的结果。

    Attributes:
        success: 是否重载成功
        message: 面向人的结果说明
        diff: 元素绑定映射的变化
    """

    success: bool
    message: str
    diff: ElementMappingDiff = field(default_factory=ElementMappingDiff)

    def render(self) -> str:
        """控制台回显文案（多行）。"""
        header = "配置热重载成功" if self.success else "配置热重载失败"
        lines = [f"{header}：{self.message}"]
        if not self.diff.is_empty():
            lines.append("元素绑定变化：")
            lines.append(self.diff.render())
        return "\n".join(lines)


def diff_element_mapping(
    old: Mapping[str, str], new: Mapping[str, str]
) -> ElementMappingDiff:
    """比较重载前后的元素绑定映射。"""
    added = {key: module for key, module in new.items() if key not in old}
    removed = {key: module for key, module in old.items() if key not in new}
    remapped = {
        key: (old[key], new[key])
        for key, module in new.items()
        if key in old and old[key] != new[key]
    }
    return ElementMappingDiff(added=added, removed=removed, remapped=remapped)


class ConfigReloadManager:
    """把 config.yaml 的新内容热灌进运行中的组件。

    组合根构造一次（普通对象，不是单例）：它持有控制器引用，所有活组件都从
    控制器上取。
    """

    def __init__(self, controller, *, config_path: str = "config.yaml"):
        self.controller = controller
        self.config_path = config_path

    def reload(self) -> ReloadReport:
        """重新读取配置并热更新各组件；失败时活配置一字不改。"""
        try:
            new_config = ConfigLoader.load_config(self.config_path)
        except Exception as exc:
            return ReloadReport(success=False, message=f"配置文件读取失败：{exc}")

        problem = self._validate(new_config)
        if problem:
            return ReloadReport(success=False, message=problem)

        old_mapping = dict(self.controller.event_manager.element_to_event)
        self._apply_in_place(new_config)
        new_mapping = self.controller.event_manager.rebind_elements()

        return ReloadReport(
            success=True,
            message=f"已应用 {self.config_path}",
            diff=diff_element_mapping(old_mapping, new_mapping),
        )

    def _validate(self, config) -> Optional[str]:
        """校验新配置；返回问题描述，通过则返回 None。

        最低要求：根是字典、soul 是字典、soul.elements 是字典 —— 少了任何一项，
        元素查找都会在每次调用时炸掉。
        """
        if not isinstance(config, dict):
            return "配置文件根节点必须是字典"
        soul = config.get("soul")
        if not isinstance(soul, dict):
            return "配置文件缺少 soul 段"
        if not isinstance(soul.get("elements"), dict):
            return "配置文件缺少 soul.elements 元素表"
        return None

    def _apply_in_place(self, new_config: dict) -> None:
        """把新配置写进各组件正在用的 dict 对象（对象身份保持不变）。"""
        root = self.controller.config
        soul_config = self.controller.soul_handler.config
        qq_music_config = self.controller.music_handler.config

        for live, section in (
            (soul_config, new_config.get("soul")),
            (qq_music_config, new_config.get("qq_music")),
        ):
            if isinstance(section, dict):
                live.clear()
                live.update(section)

        root.clear()
        root.update(new_config)
        root["soul"] = soul_config
        root["qq_music"] = qq_music_config
