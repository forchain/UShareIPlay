"""In-memory 在线用户抽屉驱动 —— 抽屉 UI 端口的离线替身。

抽屉这一层唯一的外部依赖是 Soul App 的真实屏幕，这里整块换掉：

| 真实依赖 | 替身 |
|---|---|
| `element_finder.try_find_element('online_users')`（抽屉是否开着） | `is_open`，只读内存里的开关 |
| `try_find_element('user_count')` + `click()` | `open`：成功就真的把内存里的开关置上 |
| `wait_for_element_clickable('online_users_close'/'close_button')` | `close`：按脚本决定成功与否 |
| `wait_for_element('online_users')` + 落定静默 | `wait_for_settle`：容器缺席即返回 False |
| `gesture_handler.swipe(...)` + 滑后停稳 | `scroll_container`：把窗口沿成员列表往后挪一页 |
| `find_child_elements('user_container')` → `online_user` / `follow_state` | `find_member_row`：按昵称在**当前窗口**里找 |

因此「只在抽屉是自己打开的时候才关」「正文抛异常时照样收尾」「关不掉只记警告不抛」
这类断言，考的是 `OnlineDrawerManager` 自己做的决策，而不是任何 UI 时序。

屏幕本身由 `members`（房间里有哪些在线用户）与 `page_size`（一次渲染几行）描述：
真实 Appium 里列表要靠滑才往下出，这里用 `scroll_offset` 表示已经滑过了多少行 ——
`find_member_row` 只看当前窗口这一条，就是生产端「只查已渲染的行」的等价物。

脚本化失败：`open_fails` / `close_fails` / `settle_fails` / `container_missing`
让每一条异常安全路径都能被确定性地走到。
"""

from typing import Optional

from ushareiplay.managers.online_drawer.driver import (
    DEFAULT_SCROLL_DURATION_MS,
    DEFAULT_SETTLE_TIMEOUT,
    MemberRow,
    OnlineDrawerDriverPort,
)


class InMemoryOnlineDrawerDriver(OnlineDrawerDriverPort):
    """把抽屉的开关状态与在线名单放在内存里的 UI 端口替身。

    Args:
        members: 房间里的在线用户，按列表顺序。元素是昵称字符串，或
            `(昵称, 关注关系文案)` 二元组。
        page_size: 一页渲染几行。`None` 表示全部一次渲染完，滚动永远滑不动。
        drawer_open: 初始状态。True 表示「外层流程已经打开了抽屉」。
        open_fails: 点入口打不开抽屉。
        close_fails: 关闭按钮点不到（模拟两个 `ivClose` 都没渲染出来）。
        settle_fails: 抽屉开了但容器等不到 / 落定失败。
        container_missing: 容器一律读不到（`is_open` 恒为 False）。
        journal: 可选的共享事件流。每次动作追加一条 `drawer:open` /
            `drawer:settle` / `drawer:scroll` / `drawer:find:<昵称>` /
            `drawer:close`，用来断言动作的先后顺序。
            **注意：这里没有 `drawer:back`** —— 端口里根本没有盲按返回这个原语。

    Attributes:
        scroll_offset: 已经滑过的行数，即当前窗口的起点。
        open_calls / close_calls / settle_calls: 各自被调用的次数。
        scroll_durations: 每次滑动的时长，用于断言用的是慢滑而不是惯性飞滚。
    """

    def __init__(
        self,
        *,
        members=(),
        page_size=None,
        drawer_open=False,
        open_fails=False,
        close_fails=False,
        settle_fails=False,
        container_missing=False,
        journal=None,
    ):
        self.members = [self._as_member(m) for m in members]
        self.page_size = page_size
        self.drawer_open = bool(drawer_open)
        self.open_fails = open_fails
        self.close_fails = close_fails
        self.settle_fails = settle_fails
        self.container_missing = container_missing
        self.journal = journal

        self.scroll_offset = 0
        self.open_calls = 0
        self.close_calls = 0
        self.settle_calls = 0
        self.scroll_durations = []

    async def is_open(self) -> bool:
        if self.container_missing:
            return False
        return self.drawer_open

    async def open(self, *, error_message: str) -> dict:
        self.open_calls += 1
        self._record("drawer:open")
        if self.open_fails:
            return {'error': error_message}
        self.drawer_open = True
        return {}

    async def close(self) -> bool:
        self.close_calls += 1
        if self.close_fails:
            return False
        self._record("drawer:close")
        self.drawer_open = False
        return True

    async def wait_for_settle(self, *, timeout: int = DEFAULT_SETTLE_TIMEOUT) -> bool:
        self.settle_calls += 1
        if self.settle_fails or self.container_missing:
            return False
        self._record("drawer:settle")
        return True

    async def scroll_container(
        self, *, duration_ms: int = DEFAULT_SCROLL_DURATION_MS
    ) -> bool:
        self.scroll_durations.append(duration_ms)
        if self.page_size is None:
            # 全部一次渲染完：滑不动，和生产端滑到列表底部的效果一致。
            return False
        next_offset = self.scroll_offset + self.page_size
        if next_offset >= len(self.members):
            self.scroll_offset = len(self.members)
            self._record("drawer:scroll:end")
            return False
        self.scroll_offset = next_offset
        self._record("drawer:scroll")
        return True

    async def find_member_row(self, visible_username: str) -> Optional[MemberRow]:
        # 只查当前窗口：找不到就是找不到，翻页是调用方的循环决策。
        for name, follow_state in self.visible_members():
            if name == visible_username:
                self._record(f"drawer:find:{name}")
                return MemberRow(visible_name=name, follow_state=follow_state)
        self._record(f"drawer:miss:{visible_username}")
        return None

    def visible_members(self):
        """当前这一页渲染出来的成员，按列表顺序。"""
        if self.page_size is None:
            return list(self.members)
        end = self.scroll_offset + self.page_size
        return list(self.members[self.scroll_offset:end])

    @staticmethod
    def _as_member(member):
        """成员可以是裸昵称，也可以是带关注关系的二元组。"""
        if isinstance(member, (tuple, list)):
            name = member[0]
            follow_state = member[1] if len(member) > 1 else None
            return (name, follow_state)
        return (member, None)

    def _record(self, event: str) -> None:
        if self.journal is not None:
            self.journal.append(event)
