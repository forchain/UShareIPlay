## timer_e2e（定时器端到端）

### Trigger
- **auto**：变更影响 TimerManager、timer 命令、SQLite schema/DAO、定时入队、队列消费或事件/日志输出时，单元/脚本测试通过后应运行本 playbook。
- **manual**：用户要求验证定时器行为时，必须通过真实程序、DB 加速和事件/DB 证据验证，不能只读 timer 配置。

### Scenario / Lifecycle
- **dev**：代码或配置刚变更，停止 managed process 并重新启动。
- **test**：先复用健康运行实例；没有健康实例才启动。

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
- 报告记录 trigger、scenario、lifecycle action、injection channel、DB 查询结果和必要日志片段

### OnFail
- 触发 `!dump` 收集只读证据
- 如果可修复：修改实现 → 重跑相关单元/脚本测试 → 重跑 timer E2E
- 如果受设备、Appium、DB、账号、selector 或期望行为缺失阻塞：报告 blocker、证据和下一步
- 记录到 `agent/known_issues.md` 或 `agent/questions.md`
