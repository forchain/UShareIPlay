# E2E 真实设备验收报告：!stop 中断修复 (Soul + QQ Music)

- **Run ID**: `20261106-133112-78e59e7d`
- **Target Device**: `192.168.8.151:5555` (Crownlte / Samsung Galaxy Note 9)
- **Appium Host**: `http://192.168.8.103:4723` (Appium v2.13.1)
- **Trigger / Scenario / Lifecycle**: `manual` / `dev` / `start --scenario dev` (managed PID: 65085)
- **Injection Channel**: `.agent/commands/*.cmd` (AgentCommandSpool 后台通道)
- **Readiness Gate**: `CommandReady` 满足 (`foreground_app: Soul`, `soul_ui_state: InChatReady`, `anchors: [message_content, input_box_entry]`, `ui_lock: unlocked`)

---

## 验收断言结果与证据链

| 断言项 | 结果 | 证据路径 / 关键日志摘录 / 现象 |
| :--- | :---: | :--- |
| **1. 进程不死** | **PASS** | 注入 `!stop` 及命令中断后，托管 PID `65085` 持续保持存活，无未捕获异常，无进程崩溃退出；`process-status` 返回 `alive: true`。 |
| **2. QQ Music 同步操作迅速中止** | **PASS** | 13:32:37 注入 `!stop`，正在执行的 QQ Music UI 等待立即被 `wait_for_any_element` 暂停守卫跳过：`[W]wait_for_any_element:371 - UI wait_for_any_element skipped for [...]: runtime paused by !stop`；仅 1 秒内完成退出，`ui_lock` 释放 (`13:32:38 [D]ui_session:197 - [ui_lock] released: command:lyrics`)，输出 `[W]drain:148 - Command ':lyrics 晴天' cancelled by administrative !stop`。 |
| **3. 状态与定时器暂停** | **PASS** | `13:32:37 [C]toggle_paused:280 - paused: True`<br>`13:32:38 [I]pause:52 - Timer manager paused`<br>`13:32:39 [I]_process_events_once:527 - Stopping event processing: runtime is paused by !stop`。 |
| **4. !start 恢复运行** | **PASS** | `13:32:43 [C]toggle_paused:280 - paused: False`<br>`13:32:43 [I]resume:58 - Timer manager resumed`<br>随后主循环正常处理公屏与命令响应（13:32:46 智能回复正常触发与上屏）。 |
| **5. Soul 侧既有中断能力** | **PASS** | 在 Soul 闲时/事件监控态注入 `!stop`，立即进入 `paused: True` 并在 13:33:16 暂停定时器与事件循环；注入 `!start` 在 13:33:29 恢复。 |

---

## 缺陷发现与最小修复说明

- **发现缺陷**：先前的未提交代码中，`_dispatch_meta_if_needed` 仅由控制台交互线程 `_console_input`（读取 `sys.stdin`）调用。但在后台自动化或守护进程运行（如 E2E 测试 `start --scenario dev`、systemd、Docker）时，`sys.stdin` 收到 EOF 导致控制台线程退出，后台命令通道全部由 `AgentCommandSpool` (`.agent/commands/*.cmd`) 接收。而 `AgentCommandSpool.drain()` 原先仅在主 asyncio 事件循环（`start_monitoring` 与 `_watch_active_command`）中调用，当 QQ Music 执行同步 Appium 请求阻塞事件循环时，后台注入的 `!stop` 文件无法被及时读取派发，必须等整段耗时操作做完后才会消费。
- **修复方案（Surgical Changes）**：
  1. `AgentCommandSpool` 接入 `dispatch_meta` 回调，在读取到 `!stop`/`!start` 时立即调用 `_dispatch_meta_if_needed` 消费并同步落下 `paused` 状态，不送入普通队列。
  2. `AppController` 新增后台线程 `_spool_input_loop`（50ms 轮询），使后台命令通道独立于事件循环和控制台 stdin，确保在事件循环被同步阻塞时也能瞬时感知 `!stop`。
  3. `ElementFinder.wait_for_any_element` 的 `_condition` 轮询内部增加 `if self.is_interrupted(): return None, None`，确保在已有超时等待期间收到中断能立刻提前脱出。
- **单测回归**：`tests/test_stop_command_interruption.py` 新增 `test_agent_command_spool_dispatches_meta_stop_immediately`，全套 68 个相关单测 100% 通过。

---

## 产物与环境证据

- **运行目录**: `artifacts/20261106-133112-78e59e7d/`
  - `status.json`: 记录运行期 UI 锚点、Soul 前台状态与 `ui_lock` 状态。
  - `events.jsonl`: 记录 `agent.inject.received` 与系统事件链。
  - `page_source.xml` & `screenshot.png`: `!dump` 生成的设备界面源码与截图。
  - `adb_screenshot.png`: `adb-screenshot` 真实设备截图。
  - `.agent/run.log`: 完整运行时 stdout/stderr 日志（带 13:32:37 中断关键日志）。
- **设备租约与会话清理**:
  - 本地设备租约由 `96ff986492304c1fa8384c43607152f8` 持有，测试结束后已通过 `e2e_toolbelt.py stop` 优雅退出服务并释放租约。
  - 远程环境 (`tony@192.168.8.103`) 在前置检查时暂停，测试完成后已注入 `!start` 恢复正常运行 (`13:34:31 [C]_handle_meta_command:325 - paused: False`)。
