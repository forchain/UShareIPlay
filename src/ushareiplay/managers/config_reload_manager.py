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
    """元素映射（元素 key → 值）在重载前后的变化。

    绑定映射（元素 key → 事件模块名）与选择器映射（元素 key → XPath）共用这一份
    结构：值的语义随调用方而变，「同一个 key 的值变了」在绑定映射里是改绑，
    在选择器映射里是改了 XPath。

    Attributes:
        added: 新增的元素 key → 新值
        removed: 消失的元素 key → 旧值
        remapped: 值变了的元素 key → (旧值, 新值)
    """

    added: Mapping[str, str] = field(default_factory=dict)
    removed: Mapping[str, str] = field(default_factory=dict)
    remapped: Mapping[str, Tuple[str, str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.remapped)

    def render(self) -> str:
        """控制台回显用的多行文本（每行两格缩进）。"""
        lines = [f"  + {key} → {value}" for key, value in self.added.items()]
        lines += [f"  - {key} → {value}" for key, value in self.removed.items()]
        lines += [
            f"  ~ {key}: {old} → {new}" for key, (old, new) in self.remapped.items()
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class ReloadReport:
    """一次热重载的结果。

    Attributes:
        success: 是否重载成功
        message: 面向人的结果说明
        diff: 元素 → 事件模块的绑定变化
        selector_diff: 元素 → 选择器（XPath）的变化
    """

    success: bool
    message: str
    diff: ElementMappingDiff = field(default_factory=ElementMappingDiff)
    selector_diff: ElementMappingDiff = field(default_factory=ElementMappingDiff)

    def render(self) -> str:
        """控制台回显文案（多行）。"""
        header = "配置热重载成功" if self.success else "配置热重载失败"
        lines = [f"{header}：{self.message}"]
        if not self.diff.is_empty():
            lines.append("元素绑定变化：")
            lines.append(self.diff.render())
        if not self.selector_diff.is_empty():
            lines.append("选择器变化：")
            lines.append(self.selector_diff.render())
        return "\n".join(lines)


def diff_element_mapping(
    old: Mapping[str, str], new: Mapping[str, str]
) -> ElementMappingDiff:
    """比较重载前后的「key → 值」映射（绑定映射与选择器映射共用这一处）。"""
    added = {key: value for key, value in new.items() if key not in old}
    removed = {key: value for key, value in old.items() if key not in new}
    remapped = {
        key: (old[key], value)
        for key, value in new.items()
        if key in old and old[key] != value
    }
    return ElementMappingDiff(added=added, removed=removed, remapped=remapped)


def selector_map(section: str, config: Optional[Mapping]) -> dict:
    """把某一段配置的 elements 摊平成「段前缀.元素 key → 选择器」。

    前缀让 soul 与 qq_music 的同名 key 不会在差异里撞车。
    """
    elements = config.get("elements") if isinstance(config, Mapping) else None
    if not isinstance(elements, Mapping):
        return {}
    return {f"{section}.{key}": value for key, value in elements.items()}


class ConfigReloadManager:
    """把 config.yaml 的新内容热灌进运行中的组件。

    组合根构造一次（普通对象，不是单例）：依赖在 __init__ 里显式注入，
    它自己不回头去找控制器（ADR-0009 §1）。
    """

    def __init__(
        self,
        *,
        root_config: dict,
        soul_config: dict,
        qq_music_config: dict,
        event_manager,
        command_manager,
        config_path: str = "config.yaml",
    ):
        self.root_config = root_config
        self.soul_config = soul_config
        self.qq_music_config = qq_music_config
        self.event_manager = event_manager
        self.command_manager = command_manager
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

        old_mapping = dict(self.event_manager.element_to_event)
        old_selectors = self._selectors()
        new_selectors = self._selectors(new_config)

        self._apply_in_place(new_config)
        new_mapping = self.event_manager.rebind_elements()
        self._refresh_command_parser()

        return ReloadReport(
            success=True,
            message=f"已应用 {self.config_path}；已刷新元素映射、选择器与命令定义",
            diff=diff_element_mapping(old_mapping, new_mapping),
            selector_diff=diff_element_mapping(old_selectors, new_selectors),
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

    def _selectors(self, config: Optional[dict] = None) -> dict:
        """「段.元素 key → 选择器」的摊平视图。

        不给 config 时取活配置（重载前）；给了就按生效语义取：某段在新配置里
        不是字典时，这一段仍旧沿用活配置（与 _apply_in_place 的口径一致）。
        """
        if config is None:
            return {
                **selector_map("soul", self.soul_config),
                **selector_map("qq_music", self.qq_music_config),
            }
        soul = config.get("soul")
        qq_music = config.get("qq_music")
        return {
            **selector_map(
                "soul", soul if isinstance(soul, dict) else self.soul_config
            ),
            **selector_map(
                "qq_music",
                qq_music if isinstance(qq_music, dict) else self.qq_music_config,
            ),
        }

    def _refresh_command_parser(self) -> None:
        """命令前缀 / 等级 / 模板改了要重新绑定解析器，否则改动不生效。"""
        commands = self.root_config.get("commands")
        if isinstance(commands, list):
            self.command_manager.initialize_parser(commands)

    def _apply_in_place(self, new_config: dict) -> None:
        """把新配置写进各组件正在用的 dict 对象（对象身份保持不变）。"""
        for live, section in (
            (self.soul_config, new_config.get("soul")),
            (self.qq_music_config, new_config.get("qq_music")),
        ):
            if isinstance(section, dict):
                live.clear()
                live.update(section)

        # 根配置一次性换掉：活对象先放回新内容里，中间不会出现
        # root["soul"] 指向另一个对象的半截状态。
        merged = dict(new_config)
        merged["soul"] = self.soul_config
        merged["qq_music"] = self.qq_music_config
        self.root_config.clear()
        self.root_config.update(merged)
