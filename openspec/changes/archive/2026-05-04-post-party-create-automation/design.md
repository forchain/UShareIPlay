## Overview

将“新建派对成功后自动执行命令（目前写死为 `:radio`）”改为配置驱动，并通过 `CommandReady` 事件做门控，确保命令在 Soul 聊天输入就绪后投递执行。

本设计保持动作语义最小化：**配置只描述命令字符串**，系统只负责把这些字符串按序投递到 `MessageQueue`。

## Current State (Grounded)

- 新建派对流程位于 `PartyManager`；创建成功后会：
  - 设置默认 notice
  - 自动就座
  - 直接 `MessageQueue.put_message(MessageInfo(content=":radio"))`
- `AppController._update_status_from_page_source()` 通过 page source anchors 判定 `foreground_app=="Soul"` 且 `soul_ui_state=="InChatReady"` 时，会 emit：
  - `state.ready` with `name="CommandReady"`

## Proposed Design

### 1) Config schema (`config.yaml`)

在 `soul:` 下新增：

```yaml
soul:
  post_party_create:
    enabled: true
    wait_for_command_ready: true
    commands:
      - ":radio"
```

语义：

- `enabled`: 总开关
- `wait_for_command_ready`: 是否等待 CommandReady（建议默认 true）
- `commands`: 要自动执行的命令字符串列表，**逐条投递到 MessageQueue**

### 2) One-shot latch (门闩) semantics

我们需要同时满足两个信号，并确保只执行一次：

```
party.created(new) ─────┐
                        ├─ AND + once ─> enqueue commands[]
CommandReady      ──────┘
```

要点：

- `CommandReady` 可能先于或后于 `party.created(new)`，因此不能用 sleep 替代
- 同一次 `party.created(new)` 只触发一次（即使 `CommandReady` 在后续循环里多次出现）

### 3) Integration points

推荐新增一个轻量组件（命名示例）：

- `PostPartyCreateAutomation`（或 `AutomationHooks` / `AutomationManager` 的一个子模块）

它暴露两个入口：

- `on_party_created_new()`：由 `PartyManager` 在“新建成功”点调用/emit
- `on_command_ready()`：由 `AppController` 在 emit/检测到 CommandReady 时调用/notify

组件内部维护 latch 状态：

- `party_created_pending: bool`
- `command_ready_seen: bool`（或直接看最近一次 ready 时间戳）
- `fired_for_party_id: Optional[str]`（可选，用于更强的去重）

最终动作：

- 按序遍历 `commands[]`，构造 `MessageInfo(content=<cmd>, nickname="Console")` 并投递到 `MessageQueue`

### 4) Logging & observability

建议记录两类日志（避免噪音但可定位）：

- latch 状态变化：收到 party_created / command_ready
- 执行动作：投递了哪些命令，是否跳过（disabled / empty commands）

## Edge Cases & Decisions

- **只新建触发**：不在“恢复派对/重连回房间”触发，避免重复自动执行
- **空命令列表**：`enabled=true` 但 `commands=[]` 时应安全 no-op（仅记录一次 info）
- **CommandReady 误判**：anchors 依赖 UI 文本/selector 出现在 page source；误判会导致过早投递。保留 `wait_for_command_ready=false` 作为排障回退。
- **队列串行性**：本设计假设 `MessageQueue` 消费者按序处理命令；若未来引入并发/丢弃策略，需要在实现阶段确认背压语义。

## Test Plan (Design-level)

- 单测/轻量测试（不依赖设备）：
  - latch：`party_created` 先到 vs `command_ready` 先到，均应触发一次
  - 反复 `command_ready` 不重复触发
  - `enabled=false` 或 `commands` 为空时不投递
- 最小回归脚本：
  - `python tests/test_imports.py`
  - 新增一个针对 automation latch 的测试（实现阶段补）

