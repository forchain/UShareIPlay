## command_e2e（命令端到端）

### Guard
- 满足 `CommandReady`（见 `agent/preconditions.md`）

### Advance（不满足 Guard 时）
- 等待 `status.json` 进入 `soul_ui_state == InChatReady`
- 若长期不满足：触发 `!dump`（只读）收集 page_source/screenshot 作为诊断证据

### Inject
- 通过控制台输入 `:help`（或其他安全命令）进入队列

### Assert
- `events.jsonl` 出现 `queue.enqueue → queue.drain.* → command.* → command.result`

### OnFail
- 触发 `!dump`
- 记录到 `agent/known_issues.md` 或 `agent/questions.md`

