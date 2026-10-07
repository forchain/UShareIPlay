"""In-memory 房间档案抽屉驱动 —— 抽屉 UI 端口的离线替身。

抽屉这一层唯一的外部依赖是 Soul App 的真实屏幕，这里整块换掉：

| 真实依赖 | 替身 |
|---|---|
| Appium 元素探测（抽屉是否开着） | `InMemoryRoomProfileDrawerDriver.is_open`，只读内存里的开关 |
| `ui_actions.switch_and_click`（点开抽屉） | `open_drawer`：成功就真的把内存里的开关置上 |
| `RecoveryManager.close_drawer`（点遮罩关抽屉） | `close_drawer`：按脚本决定成功与否 |
| `key_actions.press_back`（保底返回） | `press_back`：计数，并把抽屉关上 |

因此「只在窗口是自己打开的时候才关」「抽屉关不掉时最多按一次返回」这类断言，
考的是 `RoomProfileManager` 自己做的决策，而不是任何 UI 时序。
"""

from ushareiplay.managers.room_profile.driver import RoomProfileDrawerDriverPort


class InMemoryRoomProfileDrawerDriver(RoomProfileDrawerDriverPort):
    """把抽屉的开关状态放在内存里的 UI 端口替身。

    Args:
        drawer_open: 初始状态。True 表示「外层流程已经打开了抽屉」。
        fail_for: 打不开的入口 key。列出的入口一律返回 `{'error': ...}`，
            用于脚本化「第一个入口失败、回落到第二个」。
        close_drawer_works: 点遮罩能否真的关掉抽屉。False 时 `close_drawer()`
            返回 False，抽屉保持开着 —— 这是 `press_back` 保底路径的入口条件。
        back_closes: 返回键能否真的收掉一层。False 时模拟「上面还有一层选项
            列表，返回一次还没退干净」，用于验证第二次返回。
        journal: 可选的共享事件流。填入后每次抽屉动作会追加一条
            `"drawer:open:<入口>"` / `"drawer:close"` / `"drawer:back"`，
            用来与协作方的记录交错，断言「先纠偏、再编辑、最后统一关窗」。

    Attributes:
        opened_entries: 每次尝试过的入口 key，按顺序。`[]` 就是「一个打开动作
            都不该发生」的证据。
        close_attempts: 点遮罩的次数。
        back_presses: 返回键的次数。
        is_open_calls: 状态探测的次数。
    """

    def __init__(
        self,
        *,
        drawer_open=False,
        fail_for=(),
        close_drawer_works=True,
        back_closes=True,
        journal=None,
    ):
        self.drawer_open = bool(drawer_open)
        self.fail_for = set(fail_for)
        self.close_drawer_works = close_drawer_works
        self.back_closes = back_closes
        self.journal = journal
        self.opened_entries = []
        self.close_attempts = 0
        self.back_presses = 0
        self.is_open_calls = 0

    def is_open(self) -> bool:
        self.is_open_calls += 1
        return self.drawer_open

    def open_drawer(self, entry_key: str, *, error_message: str) -> dict:
        self.opened_entries.append(entry_key)
        self._record(f"drawer:open:{entry_key}")
        if entry_key in self.fail_for:
            # 抽屉没有被点开 —— 下一个入口还有机会。
            return {"error": error_message}
        self.drawer_open = True
        return {"success": True}

    def close_drawer(self) -> bool:
        self.close_attempts += 1
        if not self.close_drawer_works:
            return False
        self._record("drawer:close")
        self.drawer_open = False
        return True

    def press_back(self) -> None:
        self.back_presses += 1
        self._record("drawer:back")
        if self.back_closes:
            self.drawer_open = False

    def _record(self, event: str) -> None:
        if self.journal is not None:
            self.journal.append(event)
