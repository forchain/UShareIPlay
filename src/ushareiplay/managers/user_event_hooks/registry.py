"""用户事件钩子的事件类型注册表。

这是 5 类事件（进入 / 离开 / 返回 / 收礼物 / 专注人数联动）**唯一**的参数化
事实源：模型类、命令前缀、文案名词、报错文案、前缀示例、用户解析口径与旧钩子
方法名都在这里。DAO 与引擎都不再自带分支，新增事件类型只需在 `EVENT_HOOK_SPECS`
里加一条。

刻意保留的一处非对称：**用户解析口径按事件类型逐条声明**，不是全局默认。收礼物
命令（`receive`）历史上走 alias-group —— 主账号下发的命令，用任意分身名都要能查
到；其余事件走 single-id，只认 canonical 主账号。二者混用会让 `clear` 误删别人
的命令，所以这里是显式字段而不是「默认值 + 例外」。
"""

from dataclasses import dataclass
from enum import Enum

from ushareiplay.models.enter_event import EnterEvent
from ushareiplay.models.exit_event import ExitEvent
from ushareiplay.models.focus_event import FocusEvent
from ushareiplay.models.receive_event import ReceiveEvent
from ushareiplay.models.return_event import ReturnEvent

#: 事件类型取值，同时也是各命令的前缀词根。
ENTER = "enter"
EXIT = "exit"
RETURN = "return"
RECEIVE = "receive"
FOCUS = "focus"


class Resolution(Enum):
    """`get_by_username` / `delete_all_by_username` 认哪些 DB 用户 id。"""

    #: 只认 canonical 主账号解析出的那一个 id。
    SINGLE_ID = "single_id"
    #: 认 canonical 主账号 + 全部分身 + 原始名这一整组 id。
    ALIAS_GROUP = "alias_group"


SINGLE_ID = Resolution.SINGLE_ID
ALIAS_GROUP = Resolution.ALIAS_GROUP

#: 用户配置的钩子命令必须以这些前缀之一开头。
COMMAND_PREFIXES = (":", "：", "/", "／")


@dataclass(frozen=True)
class UserEventHookSpec:
    """一类事件钩子的全部可变参数。"""

    event_type: str
    model: type
    prefix: str
    noun: str
    error_message: str
    prefix_example: str
    resolution: Resolution
    #: 迁移前 `CommandManager.notify_*` 按属性名分发的旧钩子方法名。保留在注册表里，
    #: 是为了让后续接入方知道每个事件类型原先挂在哪个方法上。
    hook_method: str


EVENT_HOOK_SPECS = {
    ENTER: UserEventHookSpec(
        event_type=ENTER,
        model=EnterEvent,
        prefix=":enter",
        noun="进入命令",
        error_message="处理进入命令时出错",
        prefix_example='":play 歌曲名"',
        resolution=SINGLE_ID,
        hook_method="user_enter",
    ),
    EXIT: UserEventHookSpec(
        event_type=EXIT,
        model=ExitEvent,
        prefix=":exit",
        noun="离开命令",
        error_message="处理离开命令时出错",
        prefix_example='":play 歌曲名"',
        resolution=SINGLE_ID,
        hook_method="user_leave",
    ),
    RETURN: UserEventHookSpec(
        event_type=RETURN,
        model=ReturnEvent,
        prefix=":return",
        noun="返回命令",
        error_message="处理返回命令时出错",
        prefix_example='":play 歌曲名"',
        resolution=SINGLE_ID,
        hook_method="user_return",
    ),
    RECEIVE: UserEventHookSpec(
        event_type=RECEIVE,
        model=ReceiveEvent,
        prefix=":receive",
        noun="收礼物命令",
        error_message="处理收礼物命令时出错",
        prefix_example='":say 谢谢"',
        # 主账号配置的收礼物命令，对该账号的任意分身都要生效。
        resolution=ALIAS_GROUP,
        hook_method="user_gift_receive",
    ),
    FOCUS: UserEventHookSpec(
        event_type=FOCUS,
        model=FocusEvent,
        prefix=":focus",
        noun="专注人数联动命令",
        error_message="处理专注人数命令时出错",
        prefix_example='":play 歌曲名"',
        resolution=SINGLE_ID,
        hook_method="focus_count_change",
    ),
}


def spec_for(event_type: str) -> UserEventHookSpec:
    """取事件类型的注册项。未知事件类型直接 KeyError，不做静默兜底。"""
    return EVENT_HOOK_SPECS[event_type]


def all_event_types():
    """全部已注册的事件类型。"""
    return tuple(EVENT_HOOK_SPECS)
