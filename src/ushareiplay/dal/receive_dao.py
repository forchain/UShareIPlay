"""`ReceiveDao` —— 「收礼物」命令的向后兼容垫片（#436）。

实现在 `UserEventHookDAO`。这里只保留旧的类名与方法签名，但**这条不是普通的
逐字转发**：它是 5 个遗留 DAO 里唯一解析口径不同的一个，必须写清楚。

## alias-group 口径（不能改）

收礼物命令走 **alias-group**：主账号配的命令，用该账号的**任意分身名**都要查得到
也删得掉。`UserEventHookDAO` 按 `registry` 里声明的 `resolution` 分叉 ——
`RECEIVE` 声明为 `Resolution.ALIAS_GROUP`，于是 `get_by_username` /
`delete_all_by_username` 展开成 `UserDAO.get_all_associated_user_ids(username)`
（canonical 主账号 + 全部分身 + 原始名）后按 `user_id__in` 过滤。

其余 4 个事件走 single-id。两种口径混用会让 `clear` 误删别人的命令，所以这里是
注册表里的显式字段而不是「默认值 + 例外」。`tests/test_receive_dao.py` 用
canonical `Outlier` 配置、按分身 `Chainer` 查询来钉住这条行为。

旧实现本来就已经用 `user_id__in` 过滤，所以收礼物这条的 `clear` 一直是对的 ——
`sqlite3.OperationalError: near "LEFT"` 只发生在另外 4 个 single-id DAO 上。
"""

from typing import List, Optional

from ushareiplay.managers.user_event_hooks.dao import UserEventHookDAO
from ushareiplay.managers.user_event_hooks.registry import RECEIVE
from ushareiplay.models.receive_event import ReceiveEvent


class ReceiveDao:
    """`UserEventHookDAO` 在「收礼物」事件上的兼容门面（alias-group 口径）。"""

    @staticmethod
    async def create(username: str, command: str) -> ReceiveEvent:
        """为用户新建一条收礼物命令"""
        return await UserEventHookDAO.create(RECEIVE, username, command)

    @staticmethod
    async def get_by_username(username: str) -> List[ReceiveEvent]:
        """取该用户（含主账号与全部分身）的全部收礼物命令（按 id 升序）"""
        return await UserEventHookDAO.get_by_username(RECEIVE, username)

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ReceiveEvent]:
        """按 id 取单条收礼物命令"""
        return await UserEventHookDAO.get_by_id(RECEIVE, command_id)

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        """按 id 删单条收礼物命令，返回是否真的删掉了"""
        return await UserEventHookDAO.delete_by_id(RECEIVE, command_id)

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        """清空该用户（含主账号与全部分身）的全部收礼物命令，返回删除条数"""
        return await UserEventHookDAO.delete_all_by_username(RECEIVE, username)
