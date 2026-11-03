"""命令目录：从配置编译一次，供解析、权限、帮助与提示词统一查询。

`config.yaml` 的 `commands:` 是唯一事实源。目录把每条命令的前缀、模块、
等级、子命令、客房权限、睡眠拦截与帮助文案编译成不可变定义，启动时
`validate()` 校验「声明的前缀 → 可执行的 BaseCommand 模块」是否对得上。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ushareiplay.core.config_view import ConfigView
from ushareiplay.core.roles import (
    DEFAULT_COMMAND_LEVEL,
    min_command_level,
    resolve_command_level,
)

DEFAULT_COMMANDS_PATH = Path(__file__).resolve().parent.parent / "commands"

# 睡眠时段默认拦截的播放类命令。config.yaml 的 sleep.blocked_commands 可覆盖。
DEFAULT_SLEEP_BLOCKED = frozenset(
    {"play", "next", "fav", "singer", "album", "playlist", "radio"}
)

# `:help` 末尾「更多」一行展示的命令，按顺序出现。
MORE_COMMAND_PREFIXES = ("playlist", "album", "radio", "timer", "admin")

_TRIGGER_CHARS = ":：/／$＄"


class CommandCatalogueError(RuntimeError):
    """命令目录配置不自洽（缺模块、重复前缀）时抛出，启动即失败。"""


def _normalize_prefix(value: object) -> str:
    return str(value or "").strip().lstrip(_TRIGGER_CHARS).strip().lower()


def _normalize_prefixes(values: Optional[Iterable[Any]]) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = values.split(",")
    return frozenset(
        prefix for prefix in (_normalize_prefix(v) for v in values) if prefix
    )


def _defines_base_command(path: Path) -> bool:
    """模块顶层是否直接定义了 BaseCommand 子类。

    用 AST 而不是 import：启动校验不该为了看一眼类名就执行每个命令模块。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
            if name == "BaseCommand":
                return True
    return False


@dataclass(frozen=True)
class CommandDefinition:
    """一条命令的完整声明。`raw` 保留配置原文（模板、retry 等执行期字段）。"""

    prefix: str
    module: str
    level: int
    subcommands: Mapping[str, Any]
    guest_allowed: bool
    sleep_blocked: bool
    help_hint: Optional[str]
    help_order: int
    description: str
    raw: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True)
class CommandInvocation:
    """一次解析结果：命中的定义与本次参数。"""

    definition: CommandDefinition
    parameters: tuple[str, ...]

    @property
    def command_info(self) -> dict:
        """沿用旧解析器的字典形态，执行链路与模板字段无需改动。"""
        return {**self.definition.raw, "parameters": list(self.parameters)}


class CommandCatalogue:
    def __init__(
        self,
        definitions: Mapping[str, CommandDefinition],
        *,
        sleep_blocked: Iterable[str] = (),
        duplicate_prefixes: Iterable[str] = (),
        commands_path: Path = DEFAULT_COMMANDS_PATH,
    ):
        self._definitions = dict(definitions)
        self._sleep_blocked = frozenset(sleep_blocked)
        self._duplicate_prefixes = tuple(duplicate_prefixes)
        self._commands_path = Path(commands_path)

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        commands_path: Optional[Path] = None,
    ) -> "CommandCatalogue":
        """从根配置（或裸命令列表）编译目录。"""
        if isinstance(config, ConfigView):
            commands = config.command_entries
            sleep_section = config.maybe_section("sleep")
            sleep_cfg = dict(sleep_section.data) if sleep_section else {}
        else:
            if not isinstance(config, dict):
                config = {"commands": config}

            commands = config.get("commands")
            if not isinstance(commands, list):
                commands = []

            sleep_cfg = config.get("sleep")
            if not isinstance(sleep_cfg, dict):
                sleep_cfg = {}
        blocked_raw = sleep_cfg.get("blocked_commands")
        configured_blocked = (
            _normalize_prefixes(blocked_raw)
            if blocked_raw is not None
            else DEFAULT_SLEEP_BLOCKED
        )

        definitions: dict[str, CommandDefinition] = {}
        duplicates = []
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            prefix = _normalize_prefix(command.get("prefix"))
            if not prefix:
                continue
            if prefix in definitions:
                duplicates.append(prefix)
                continue

            module = str(command.get("module") or prefix).strip()
            level = int(command.get("level", DEFAULT_COMMAND_LEVEL))
            subcommands = command.get("subcommands")
            if not isinstance(subcommands, dict):
                subcommands = {}
            help_hint = str(command.get("help") or "").strip() or None
            try:
                help_order = int(command.get("help_order", index))
            except (TypeError, ValueError):
                help_order = index

            definitions[prefix] = CommandDefinition(
                prefix=prefix,
                module=module,
                level=level,
                subcommands=subcommands,
                guest_allowed=bool(command.get("guest_allowed", False)),
                sleep_blocked=bool(
                    command.get("sleep_blocked", prefix in configured_blocked)
                ),
                help_hint=help_hint,
                help_order=help_order,
                description=str(command.get("description") or "").strip(),
                raw=command,
            )

        return cls(
            definitions,
            sleep_blocked=configured_blocked,
            duplicate_prefixes=duplicates,
            commands_path=commands_path or DEFAULT_COMMANDS_PATH,
        )

    def validate(self, commands_path: Optional[Path] = None) -> None:
        """校验目录自洽；不通过则抛 CommandCatalogueError。"""
        base = Path(commands_path) if commands_path is not None else self._commands_path
        problems = [
            f"重复的命令前缀: {prefix}" for prefix in self._duplicate_prefixes
        ]
        for definition in self._definitions.values():
            module_path = base / f"{definition.module}.py"
            if not module_path.is_file():
                problems.append(
                    f"命令 '{definition.prefix}' 声明的模块 {definition.module}.py 不存在"
                )
                continue
            if not _defines_base_command(module_path):
                problems.append(
                    f"命令 '{definition.prefix}' 的模块 {definition.module}.py "
                    "没有定义 BaseCommand 子类"
                )
        if problems:
            raise CommandCatalogueError("; ".join(problems))

    @property
    def definitions(self) -> tuple[CommandDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, command: object) -> Optional[CommandDefinition]:
        return self._definitions.get(self._prefix_of(command))

    def resolve(self, text: object) -> Optional[CommandInvocation]:
        """解析一条已归一化的命令文本；前缀大小写不敏感。"""
        if not text:
            return None
        parts = str(text).strip().lstrip(_TRIGGER_CHARS).strip().split()
        if not parts:
            return None
        definition = self._definitions.get(parts[0].lower())
        if definition is None:
            return None
        return CommandInvocation(definition=definition, parameters=tuple(parts[1:]))

    def required_level(self, command: object, parameters: Iterable[str] = ()) -> int:
        definition = self.get(command)
        if definition is None:
            return DEFAULT_COMMAND_LEVEL
        return resolve_command_level(definition.raw, list(parameters))

    def is_guest_allowed(self, command: object) -> bool:
        definition = self.get(command)
        return bool(definition and definition.guest_allowed)

    def is_sleep_blocked(self, command: object) -> bool:
        prefix = self._prefix_of(command)
        if not prefix:
            return False
        definition = self._definitions.get(prefix)
        if definition is not None:
            return definition.sleep_blocked
        return prefix in self._sleep_blocked

    def get_help_lines(self) -> list[str]:
        helpers = sorted(
            (d for d in self._definitions.values() if d.help_hint),
            key=lambda d: d.help_order,
        )
        lines = ["帮助"] + [d.help_hint for d in helpers]
        more = [p for p in MORE_COMMAND_PREFIXES if p in self._definitions]
        if more:
            lines.append("更多: " + "/".join(f":{prefix}" for prefix in more))
        return lines

    def get_prompt_lines(self, *, guest_room: bool = False) -> list[str]:
        """LLM 系统提示里的命令表；客房模式只列客房可用命令。"""
        lines = []
        for definition in self._definitions.values():
            if guest_room and not definition.guest_allowed:
                continue
            level = min_command_level(definition.raw)
            description = definition.description or definition.prefix
            lines.append(f"- `:{definition.prefix}` (所需等级: L{level}): {description}")
        return lines

    def modules(self) -> tuple[str, ...]:
        return tuple(d.module for d in self._definitions.values())

    @staticmethod
    def _prefix_of(command: object) -> str:
        if isinstance(command, CommandDefinition):
            return command.prefix
        if isinstance(command, Mapping):
            return _normalize_prefix(command.get("prefix"))
        return _normalize_prefix(command)
