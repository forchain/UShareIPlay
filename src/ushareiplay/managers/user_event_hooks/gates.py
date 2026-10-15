"""事件前置闸门：一次事件该不该真的触发，以及该以谁的名义触发。

绝大多数事件是「谁发生了就发给谁」，不需要前置判断。只有「离开」事件有一种例外：
同一个人可以有多个分身（alias），Soul 的在线用户列表里每个分身各占一行。一个分身
退出了，并不代表这个人真的走了 —— 只要还有一个分身留在房间里，这次离开就不能触发
退出命令，否则主账号下的 `:exit` 命令会被分身的进进出出反复触发。

判定要求拿到「这个人的全部分身」，因此它必须发生在命令执行之后、入队之前，也就是
`UserEventHooks.fire()` 内部。这个文件把该判定连同随之而来的 canonical 解析和记忆
沉淀调度收在一起，引擎只按事件类型查表，不自带分支。

单独成文件而不是内联进 `manager.py` 的理由是边界：引擎文件正被其它并行改动触碰，
而闸门本身是「离开」这一类事件的专属关注点，留在自己的文件里既好读也便于单独回退。

关于 `InfoManager.instance()` 未做守卫：`InfoManager` 未初始化时抛出的 `SingletonError`
会一路上抛给 `fire()` 的异常处理，记一条错误日志并返回 0 —— 与迁移前
`CommandManager.notify_user_leave` 外层 `except` 的行为一致（这一次离开事件不会
触发任何命令）。这里刻意不改成静默兜底。
"""

from typing import Awaitable, Callable, Dict, Optional

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.managers.info_manager import InfoManager
from ushareiplay.managers.memory_manager import MemoryManager
from ushareiplay.managers.user_event_hooks.registry import EXIT

#: 闸门签名：`(可见昵称) -> 触发目标用户名`。
#:
#: 返回 `None` 表示「这一次事件不该触发」；返回字符串表示触发目标 —— 对「离开」
#: 而言那是 DB 侧的 canonical 主账号名，因为退出命令是按主账号配置的。
ExitGate = Callable[..., Awaitable[Optional[str]]]


async def resolve_exit_target(
    username: str,
    log_info: Optional[Callable[[str], None]] = None,
    log_warning: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """「离开」闸门：全部分身都离线才放行，并以主账号名触发。

    Args:
        username: 触发者的可见昵称（UI 侧名字）。
        log_info: 信息级日志回调。
        log_warning: 告警级日志回调（记忆沉淀调度失败时用）。

    Returns:
        canonical 主账号名；任一分身仍在线时返回 `None`。
    """
    log_info = log_info or (lambda *_args, **_kwargs: None)
    log_warning = log_warning or (lambda *_args, **_kwargs: None)

    all_avatars = await UserDAO.get_all_avatar_usernames(username)
    online_users = InfoManager.instance().get_online_users()
    still_online = all_avatars & online_users

    if still_online:
        log_info(
            f"User leave skipped for '{username}': avatars still online: {still_online}"
        )
        return None

    # 以主账号 canonical username 触发退出事件
    raw_user = await UserDAO.get_or_create_raw(username)
    canonical_user = await UserDAO.resolve_canonical(raw_user)
    canonical_username = canonical_user.username

    log_info(
        f"All avatars offline for '{username}' → triggering user_leave "
        f"as canonical '{canonical_username}'"
    )

    # 为离开的用户（主账号）安排记忆沉淀
    try:
        if MemoryManager.is_initialized():
            MemoryManager.instance().schedule_consolidation_user(canonical_username)
    except Exception:
        log_warning(
            f"Failed to schedule memory consolidation for user_leave "
            f"'{canonical_username}'"
        )

    return canonical_username


#: 事件类型 -> 闸门。没有条目的事件类型不受任何前置条件约束。
GATES: Dict[str, ExitGate] = {
    EXIT: resolve_exit_target,
}
