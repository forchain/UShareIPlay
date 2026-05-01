## timer_e2e（定时器端到端）

### Guard
- 满足 `CommandReady`
- DB 可访问（SQLite）

### Advance（加速策略）
- 通过 SQL 将目标 timer 的 `next_trigger` 更新为 `now + 2s`（不改变业务逻辑，只改变触发时刻）

### Inject
- 可选：注入 `:timer` / 或测试专用命令

### Assert
- `events.jsonl` 出现定时器触发相关事件（若已埋点）或队列出现来自 Timer 的入队消息
- DB 中 timer 的 `next_trigger` 被更新（repeat）或记录被删除（non-repeat）

### OnFail
- 触发 `!dump` 收集只读证据
- 记录到 `agent/known_issues.md`

