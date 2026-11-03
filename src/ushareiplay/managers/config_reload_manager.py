"""配置热重载（#469）：把 config.yaml 的新内容热灌进运行中的组件。

流程刻意分成两段：

1. 读盘 + 校验 —— 这一段任何失败都不动活配置（半截的 / 走样的 config.yaml
   绝不能把跑着的机器人变成砖头：ElementFinder 每次查元素都会读配置）；
2. 原地写入 + 重绑元素映射 —— 这一段成功才算热重载完成。

「原地写入」是关键：`ElementFinder`、`EventManager` 等组件缓存的是
`handler.config` 这个段视图，热重载靠视图换内容生效（ADR-0012）。
"""

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.config_view import ConfigError, ConfigView


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
        config: ConfigView,
        event_manager,
        command_manager,
        config_path: str = "config.yaml",
    ):
        self.config = config
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

        self.config.reload(new_config)
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

        校验的是「机器人启动时必须有的东西」：少了任何一项，机器人要么起不来
        （app_controller 读 config["qq_music"] / config["commands"] 会 KeyError），
        要么一用就炸（元素查找读 config["elements"] 会 KeyError）。这种配置不该
        被热重载接受 —— 接受了就等于把机器人推进一个重启也起不来的状态。
        必需元素清单与启动期校验共用 `ConfigView.validate_required_elements`，
        两个门禁对「什么样的配置能启动」只有一份定义。
        """
        if not isinstance(config, dict):
            return "配置文件根节点必须是字典"
        soul = config.get("soul")
        if not isinstance(soul, dict):
            return "配置文件缺少 soul 段"
        if not isinstance(soul.get("elements"), dict):
            return "配置文件缺少 soul.elements 元素表"
        qq_music = config.get("qq_music")
        if not isinstance(qq_music, dict):
            return "配置文件缺少 qq_music 段"
        if not isinstance(qq_music.get("elements"), dict):
            return "配置文件缺少 qq_music.elements 元素表"
        if not isinstance(config.get("commands"), list):
            return "配置文件缺少 commands 命令表"
        try:
            ConfigView(config).validate_required_elements()
        except ConfigError as exc:
            return f"配置文件缺少启动期必需的元素：{exc}"
        return None

    def _selectors(self, config: Optional[dict] = None) -> dict:
        """「段.元素 key → 选择器」的摊平视图。

        不给 config 时取活配置（重载前）；给了就按即将生效的新配置取。
        """
        if config is None:
            return {
                **selector_map("soul", self.config.soul.data),
                **selector_map("qq_music", self.config.music.data),
            }
        soul = config.get("soul")
        qq_music = config.get("qq_music")
        return {
            **selector_map(
                "soul", soul if isinstance(soul, dict) else self.config.soul.data
            ),
            **selector_map(
                "qq_music",
                qq_music if isinstance(qq_music, dict) else self.config.music.data,
            ),
        }

    def _refresh_command_parser(self) -> None:
        """命令前缀 / 等级 / 模板 / 权限改了要重新编译目录，否则改动不生效。"""
        self.command_manager.initialize_parser(self.config)
        catalogue = self.command_manager.catalogue

        # 睡眠拦截与客房权限各自持有一份目录引用；不换的话热重载只刷新了解析器。
        from ushareiplay.managers.sleep_manager import SleepManager
        from ushareiplay.state.room_state import RoomState

        if SleepManager.is_initialized():
            SleepManager.instance().configure_catalogue(catalogue)
        if RoomState.is_initialized():
            RoomState.instance().configure_catalogue(catalogue)
