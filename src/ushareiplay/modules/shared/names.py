"""两个命名域的值对象：可见昵称（分身名）与 canonical 名（主账号名）。

归一化口径来自现有的 InfoManager / UserManager 行为：跨命名域的身份比较按
`username.strip()` 逐字进行、大小写敏感；空名字保持为空，由调用方决定如何处理。
两个值对象是不同的类型，因此永远不会相等 —— 这正是「禁止拿可见名与 canonical
名做字符串相等比较」在类型上的落点（docs/users.md）。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class _Name:
    value: str

    def __post_init__(self):
        object.__setattr__(self, "value", self.value.strip())

    def __str__(self) -> str:
        return self.value

    def __bool__(self) -> bool:
        return bool(self.value)


class VisibleName(_Name):
    """Soul UI 唯一渲染出来的昵称（分身名）。"""


class CanonicalName(_Name):
    """DB `users.username` 的规范名（主账号名）。"""
