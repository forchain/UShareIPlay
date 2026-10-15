"""钩子命令入队前的宏展开，以及 UI 可见昵称 → DB canonical 名的命名域解析。

专注人数联动是唯一带宏的事件类型。`{username}` / `{seat}` / `{action}` 这一族宏的
数据源是事件上下文里的座位观测 `seat_info`（键名见 `SEAT_INFO_CTX_KEY`）：键是
Soul UI 上可见的分身名，值是该用户本次观测到的**座位**号与动作。

观测键与钩子归属名分属两个命名域 —— 观测键是分身名，钩子挂在 DB 解析后的主账号名
上，两者字符串不同。`seat_info_for` 因此先按原名取，取不到再按
`UserDAO.get_identity_usernames` 给出的同一身份（主账号 + 全部分身）名字集合匹配
一次；直接写 `seat_info[username]` 会落空。

**`{user_name}` 不属于这一族。** 它是 intake 层的宏，由
`chat_intake.expand_queue_text` 在队列 drain 期、且只在队列文法那条路上展开。因此
这里只负责把命令**投进 `MessageQueue`**；引擎一旦绕过队列直接执行，用户配置的
`{user_name}` 就会静默失效。

这个模块刻意不 import 引擎与注册表：#424 / #429 在平行分支上改这两个文件，把宏与
身份解析单独放一处可以让三方改动互不覆盖。
"""

from ushareiplay.dal.user_dao import UserDAO

#: 座位观测数据在事件上下文（`UserEventHooks.fire` 的 `ctx`）里的键名。
SEAT_INFO_CTX_KEY = "seat_info"


async def seat_info_for(username: str, seat_info: dict) -> dict:
    """取该用户本次观测到的座位信息（`{seat}` / `{action}` 宏的数据源）。

    两级查找：先按原名精确取（调用方已经传了 canonical 名且观测也按 canonical 记的
    情况），取不到再在同一身份的名字集合里扫一遍（观测键是分身名的常态）。

    DAO 异常时返回空 dict —— 宏取不到值只应该让宏变成空串，不该炸掉整批入队。
    """
    info = seat_info.get(username)
    if info:
        return info

    try:
        identity = await UserDAO.get_identity_usernames(username)
    except Exception:
        return {}

    for observed_name, observed_info in seat_info.items():
        if observed_name in identity:
            return observed_info
    return {}


async def expand_seat_macros(command: str, username: str, ctx: dict) -> str:
    """把座位宏替换成本次观测值。`username` 是钩子的归属人（DB canonical 名）。

    替换顺序是 `{username}` → `{seat}` → `{action}`，与迁移前 `focus.py` 一致。
    观测缺失时替换成空串而不是留下字面量：`:focus add ":seat {seat}"` 在没观测到
    这个人时发出来是 `:seat `，不会把宏原样喊到公屏上。座位号非字符串时按 `str()`
    归一（`int 3` → `"3"`）。
    """
    observed = await seat_info_for(username, (ctx or {}).get(SEAT_INFO_CTX_KEY) or {})
    return (
        command
        .replace("{username}", username)
        .replace("{seat}", str(observed.get("seat_number", "")))
        .replace("{action}", str(observed.get("action", "")))
    )
