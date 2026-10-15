"""用户事件钩子深度模块的契约层。

用户可以为「进入 / 离开 / 返回 / 收礼物 / 专注人数联动」这 5 类事件配置自己的
命令（如 `:enter add ":play 稻香"`）。以前这件事散成 5 份近克隆的命令 + 5 份
近克隆的 DAO，解析规则、前缀校验和文案各写一遍，改一处要改五处。

这个子包把它收成一个窄接口，命令层只需要知道两件事：

- `execute_crud(event_type, username, raw_content)` —— 拿到一条配置命令，按事件类型
  返回要给用户看的 `{'message': ...}` / `{'error': ...}`；
- `fire(event_type, username, ctx)` —— 事件发生了，把该用户配置的钩子命令投进
  运行时队列。

shlex 解析、前缀校验（`:` `：` `/` `／`）、四个子动作（`add`/`del`/`list`/`clear`）、
五类事件各自的文案、以及「收礼物命令按 alias-group、其余按 single-id 解析用户」这条
容易踩坑的非对称规则，都在这个子包内部。`registry.py` 是事件类型的唯一事实源，
`dao.py` 是参数化持久化，`manager.py` 是上面两个入口。
"""

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.manager import UserEventHooks
from ushareiplay.managers.user_event_hooks.registry import (
    ALIAS_GROUP,
    COMMAND_PREFIXES,
    ENTER,
    EVENT_HOOK_SPECS,
    EXIT,
    FOCUS,
    RECEIVE,
    RETURN,
    SINGLE_ID,
    Resolution,
    UserEventHookSpec,
    all_event_types,
    spec_for,
)

__all__ = [
    "ALIAS_GROUP",
    "COMMAND_PREFIXES",
    "ENTER",
    "EVENT_HOOK_SPECS",
    "EXIT",
    "FOCUS",
    "RECEIVE",
    "RETURN",
    "SINGLE_ID",
    "Resolution",
    "UserEventHookDAO",
    "UserEventHookSpec",
    "UserEventHooks",
    "all_event_types",
    "spec_for",
]
