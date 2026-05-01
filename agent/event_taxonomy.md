## events.jsonl 事件字典（最小断言集）

### 核心字段

每条事件必须包含：
- `schema_version`（int）
- `ts`（ISO8601）
- `level`（string）
- `event`（string）
- `run_id`（string）
- `ctx`（object）

可选：
- `trace_id`（string）

### 最小断言链（命令 E2E）

1. `queue.enqueue`
2. `queue.drain.start`
3. `command.received`
4. `command.dispatch`
5. `command.result`
6. `queue.drain.end`

### 状态/就绪

- `state.snapshot`：更新 `status.json` 的时刻
- `state.ready`：声明 `CommandReady`（必须包含 anchors 与 foreground_app）

### 只读证据

- `artifact.page_source`
- `artifact.screenshot`

