"""In-memory 房间档案抽屉驱动 —— 抽屉 UI 端口的离线替身。

抽屉这一层唯一的外部依赖是 Soul App 的真实屏幕，这里整块换掉：

| 真实依赖 | 替身 |
|---|---|
| Appium 元素探测（抽屉是否开着） | `InMemoryRoomProfileDrawerDriver.is_open`，只读内存里的开关 |
| `ui_actions.switch_and_click`（点开抽屉） | `open_drawer`：成功就真的把内存里的开关置上 |
| `RecoveryManager.close_drawer`（点遮罩关抽屉） | `close_drawer`：按脚本决定成功与否 |
| `key_actions.press_back`（保底返回） | `press_back`：计数，并把抽屉关上 |
| `element_finder.wait_for_element_clickable` | `click_element`：元素在内存里才点得动 |
| `element_finder.wait_for_any_element` | `wait_for_any`：按传入顺序返回第一个命中的 key |
| `element.clear()` + `send_keys()` | `replace_text`：记进 `typed` |

因此「只在窗口是自己打开的时候才关」「抽屉关不掉时最多按一次返回」这类断言，
考的是 `RoomProfileManager` 自己做的决策，而不是任何 UI 时序。

屏幕本身由 `present`（当前存在哪些 key）与 `world_after_click`（点某个 key 之后
屏幕变成什么样）两个参数描述。真实 Appium 里「点确认之后编辑层消失、聊天框出现」
是一次界面切换，这里用 `world_after_click` 把那次切换写成数据。
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
        present: 屏幕当前存在哪些 selector key（可点击即存在）。默认空。
        world_after_click: `{"<被点的 key>": ("<点击后存在的 key>", ...)}`，
            用于脚本化「点确认之后编辑层消失」这类界面切换。未列出的点击不影响
            屏幕。

    Attributes:
        opened_entries: 每次尝试过的入口 key，按顺序。`[]` 就是「一个打开动作
            都不该发生」的证据。
        close_attempts: 点遮罩的次数。
        back_presses: 返回键的次数。
        is_open_calls: 状态探测的次数。
        clicks: 点过的 key，按顺序（坐标点击也算一次点击）。
        coordinate_clicks: `(key, y_ratio)` 序列，按顺序，只含坐标点击。
        typed: `(key, 文本)` 序列，按顺序。
        waits: `wait_for_any` 查过的 key 元组，按顺序。
    """

    def __init__(
        self,
        *,
        drawer_open=False,
        fail_for=(),
        close_drawer_works=True,
        back_closes=True,
        journal=None,
        present=(),
        world_after_click=None,
    ):
        self.drawer_open = bool(drawer_open)
        self.fail_for = set(fail_for)
        self.close_drawer_works = close_drawer_works
        self.back_closes = back_closes
        self.journal = journal
        self.present = set(present)
        self.world_after_click = {
            key: tuple(value) for key, value in (world_after_click or {}).items()
        }
        self.opened_entries = []
        self.close_attempts = 0
        self.back_presses = 0
        self.is_open_calls = 0
        self.clicks = []
        self.coordinate_clicks = []
        self.typed = []
        self.waits = []
        self.swipes = []

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
            self.present.discard("party_setting_container")

    def click_element(self, key: str, *, timeout: int = 10) -> bool:
        if key not in self.present:
            return False
        self.clicks.append(key)
        self._record(f"element:click:{key}")
        if key in self.world_after_click:
            self.present = set(self.world_after_click[key])
        return True

    def click_element_at(self, key: str, *, y_ratio: float, timeout: int = 10) -> bool:
        """坐标点击。语义与 `click_element` 完全一致，另外把比例记进
        `coordinate_clicks`，好断言「房名编辑入口点的是 0.25 高度而不是中心」。"""
        if key not in self.present:
            return False
        self.coordinate_clicks.append((key, y_ratio))
        self.clicks.append(key)
        self._record(f"element:click-at:{key}:{y_ratio}")
        if key in self.world_after_click:
            self.present = set(self.world_after_click[key])
        return True

    def wait_for_any(self, keys, *, timeout: int = 10):
        self.waits.append(tuple(keys))
        for key in keys:
            if key in self.present:
                return key
        return None

    def replace_text(self, key: str, text: str, *, timeout: int = 10) -> bool:
        if key not in self.present:
            return False
        self.typed.append((key, text))
        self._record(f"element:type:{key}")
        return True

    def scroll_container_until_element(
        self,
        element_key: str,
        container_key: str,
        direction: str = "up",
        attribute_name=None,
        attribute_value=None,
        max_swipes: int = 10,
    ):
        self.swipes.append((element_key, container_key, direction))
        self._record(f"scroll:{container_key}:{direction}:{element_key}")
        if element_key in self.present:
            class _Elem:
                text = getattr(self, "texts", {}).get(element_key, "")
                def click(elem_self):
                    self.clicks.append(element_key)
                    self._record(f"element:click:{element_key}")
                    if element_key in self.world_after_click:
                        self.present = set(self.world_after_click[element_key])
                    return True
            elem = _Elem()
            return element_key, elem, [elem.text]
        return None, None, []

    def is_settings_open(self) -> bool:
        return "party_setting_container" in self.present

    def _record(self, event: str) -> None:
        if self.journal is not None:
            self.journal.append(event)
