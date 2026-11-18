"""命令领域：目录声明、睡眠窗口与命令规则异常。

`config.yaml` 的 `commands:` 是唯一事实源。目录把每条命令的前缀、模块、
等级、子命令、客房权限、睡眠拦截与帮助文案编译成不可变定义，启动时
`validate()` 校验「声明的前缀 → 可执行的 BaseCommand 模块」是否对得上。
"""

from __future__ import annotations

import ast
import datetime as dt
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.errors import DomainError
from ushareiplay.modules.shared.roles import (
    DEFAULT_COMMAND_LEVEL,
    min_command_level,
    resolve_command_level,
)

DEFAULT_COMMANDS_PATH = Path(__file__).resolve().parents[2] / "commands"
CHAT_COMMANDS_PATH = Path(__file__).resolve().parents[2] / "adapters" / "inbound" / "chat"
# 迁移期命令按序查找：新的聊天适配器优先，旧 commands 包随后（#559 删除后者）。
DEFAULT_COMMAND_ROOTS = (CHAT_COMMANDS_PATH, DEFAULT_COMMANDS_PATH)

# 睡眠时段默认拦截的播放类命令。config.yaml 的 sleep.blocked_commands 可覆盖。
DEFAULT_SLEEP_BLOCKED = frozenset(
    {"play", "next", "fav", "singer", "album", "playlist", "radio"}
)

# `:help` 末尾「更多」一行展示的命令，按顺序出现。
MORE_COMMAND_PREFIXES = ("playlist", "album", "radio", "timer", "admin")

DEFAULT_SLEEP_ENABLED = True
DEFAULT_SLEEP_WINDOW_START = dt.time(23, 0)
DEFAULT_SLEEP_WINDOW_END = dt.time(6, 0)

_TRIGGER_CHARS = ":：/／$＄"


class CommandCatalogueError(DomainError):
    """命令目录配置不自洽（缺模块、重复前缀）时抛出，启动即失败。"""


class InsufficientCommandLevel(DomainError):
    """调用者等级低于该命令（或该子命令形态）要求的门槛。"""

    def __init__(self, required_level: int, user_level: int):
        super().__init__(required_level, user_level)
        self.required_level = required_level
        self.user_level = user_level


class SleepBlocked(DomainError):
    """睡眠时段内触发了被拦截的命令。"""


class GuestRoomRestricted(DomainError):
    """他人房间（客房模式）下触发了仅限本房的管理命令。"""


class UnknownCommand(DomainError):
    """解析到的前缀没有可执行的命令对象。"""

    def __init__(self, prefix: str):
        super().__init__(prefix)
        self.prefix = prefix


@dataclass(frozen=True)
class SleepWindow:
    """睡眠时段：起止时间，跨午夜时分为两段。"""

    start: dt.time
    end: dt.time

    def contains(self, now: dt.time) -> bool:
        # start == end means "all day"
        if self.start == self.end:
            return True
        # Non-cross-midnight window: start <= t < end
        if self.start < self.end:
            return self.start <= now < self.end
        # Cross-midnight window: [start, 24:00) U [00:00, end)
        return now >= self.start or now < self.end


def parse_hhmm(value: object) -> Optional[dt.time]:
    if not isinstance(value, str):
        return None
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        return dt.time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        return None


def parse_enabled(value: object, default: bool) -> bool:
    """
    Parse a config value into a boolean without Python's `bool(x)` pitfalls.

    Supported:
    - bool: returned as-is
    - int: 0 -> False, non-zero -> True
    - str: common true/false spellings (case-insensitive, surrounding whitespace ignored)
    """
    if value is None:
        return default

    # bool is a subclass of int; check it first.
    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "y", "on"}:
            return True
        if s in {"false", "0", "no", "n", "off"}:
            return False
        return default

    return default


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
        command_roots: Iterable[Path] = DEFAULT_COMMAND_ROOTS,
    ):
        self._definitions = dict(definitions)
        self._sleep_blocked = frozenset(sleep_blocked)
        self._duplicate_prefixes = tuple(duplicate_prefixes)
        self._command_roots = tuple(Path(root) for root in command_roots)

    @property
    def command_roots(self) -> tuple[Path, ...]:
        return self._command_roots

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

        roots = (
            (Path(commands_path),) if commands_path is not None else DEFAULT_COMMAND_ROOTS
        )
        return cls(
            definitions,
            sleep_blocked=configured_blocked,
            duplicate_prefixes=duplicates,
            command_roots=roots,
        )

    def validate(self, commands_path: Optional[Path] = None) -> None:
        """校验目录自洽；不通过则抛 CommandCatalogueError。"""
        roots = (Path(commands_path),) if commands_path is not None else self._command_roots
        problems = [
            f"重复的命令前缀: {prefix}" for prefix in self._duplicate_prefixes
        ]
        for definition in self._definitions.values():
            module_path = next(
                (
                    root / f"{definition.module}.py"
                    for root in roots
                    if (root / f"{definition.module}.py").is_file()
                ),
                None,
            )
            if module_path is None:
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


# ---------------------------------------------------------------------------
# Keyword replies（#547）：关键字值对象、模式规则与 ACL 判定。
# ---------------------------------------------------------------------------

KEYWORD_MODE_SEQUENCE = "sequence"
KEYWORD_MODE_RANDOM = "random"

_KEYWORD_MODE_ALIASES = {
    "sequence": KEYWORD_MODE_SEQUENCE,
    "sequential": KEYWORD_MODE_SEQUENCE,
    "ordered": KEYWORD_MODE_SEQUENCE,
    "random": KEYWORD_MODE_RANDOM,
}


class KeywordError(DomainError):
    """关键字规则失败。"""


class KeywordNotFound(KeywordError):
    def __init__(self, keyword: str):
        super().__init__(keyword)
        self.keyword = keyword


class ConfigKeywordImmutable(KeywordError):
    """配置关键字（creator_id is None）不允许修改/删除/授权。"""


class NotKeywordOwner(KeywordError):
    """只有创建者本人能修改/删除/授权私有关键字。"""


class KeywordAlreadyPublic(KeywordError):
    """公开关键字不需要授权。"""


class KeywordNotPublic(KeywordError):
    """非公开关键字才有授权名单。"""


class MissingGrantees(KeywordError):
    """授权/取消授权缺少目标用户。"""


class KeywordEmpty(KeywordError):
    """关键字文本为空。"""


class NoKeywordsAdded(KeywordError):
    """没有关键字被添加（全部被拒绝）。"""


class UserNotOnline(KeywordError):
    """只有在线用户才能添加关键字。"""


def normalize_keyword_mode(mode: Optional[str]) -> str:
    """把配置/命令里的模式别名归一成 sequence / random。"""
    raw = (mode or KEYWORD_MODE_SEQUENCE).strip().lower()
    return _KEYWORD_MODE_ALIASES.get(raw, KEYWORD_MODE_SEQUENCE)


def pick_keyword_command(command_text: str, mode: Optional[str], chooser=random.choice) -> str:
    """按模式选出要执行的命令文本；random 从 `;` 分隔的候选里随机取一条。"""
    if normalize_keyword_mode(mode) != KEYWORD_MODE_RANDOM:
        return command_text

    candidates = [part.strip() for part in command_text.split(';') if part.strip()]
    if not candidates:
        return command_text
    return chooser(candidates)


def render_keyword_command(command_text: str, username: str, params: str = "") -> str:
    """替换关键字命令里的 `{user_name}` 与 `{params}` 占位符。"""
    return command_text.replace('{user_name}', username).replace('{params}', params or "")


@dataclass(frozen=True)
class ResolvedMention:
    """自然语言兜底解析出的命令或回复（#548 会接管解析器实现）。"""

    type: str
    content: str


@dataclass(frozen=True)
class Keyword:
    """一条关键字：配置关键字 creator_id 为 None，用户关键字记录创建者与白名单。"""

    keyword: str
    command: str
    mode: str = KEYWORD_MODE_SEQUENCE
    creator_id: Optional[int] = None
    creator_username: Optional[str] = None
    creator_level: int = 0
    is_public: bool = True
    allowed_user_ids: tuple[int, ...] = ()

    @property
    def is_config(self) -> bool:
        return self.creator_id is None

    def allows(self, user_id: Optional[int]) -> bool:
        """能否执行：公开、创建者本人，或显式授权名单。"""
        if self.is_public:
            return True
        if user_id is None:
            return False
        if self.creator_id is not None and self.creator_id == user_id:
            return True
        return user_id in self.allowed_user_ids
