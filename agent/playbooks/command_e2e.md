## command_e2e（命令端到端）

### Trigger
- **auto**：功能变更影响命令解析、命令输出、队列消费、日志/事件、DB 副作用、UI 可见反馈或跨组件工作流，且相关单元/脚本测试已通过时，Agent 应自行运行本 playbook。
- **manual**：用户明确要求测试某个命令或怀疑某个命令行为异常时，必须运行真实程序并注入命令；静态检查配置或源码只能作为辅助证据。

### Scenario / Lifecycle
- **dev**：刚完成代码或配置改动时，停止 managed process 并重新启动，确保测试的是最新代码。
- **test**：只是验证当前功能时，先检查 managed PID、fresh `status.json`、fresh `events.jsonl` 和 readiness；健康则复用，不健康或未启动才启动。
- 使用 `scripts/agent_e2e.py --scenario dev|test --trigger auto|manual --command ':xxx'`。

### Guard
- 满足 `CommandReady`（见 `agent/preconditions.md`）
- 复用进程时必须存在可用后台注入通道（`.agent/commands/*.cmd` spool）

### Advance（不满足 Guard 时）
- 等待 `status.json` 进入 `soul_ui_state == InChatReady`
- 若长期不满足：触发 `!dump`（只读）收集 page_source/screenshot 作为诊断证据

### Inject
- 通过 runner stdin 或 `.agent/commands/*.cmd` 后台 spool 注入 `:help`（或其他安全命令）进入同一条 console/queue 路径

### Assert
- `events.jsonl` 出现 `queue.enqueue → queue.drain.* → command.* → command.result`
- 按测试目标补充日志断言、DB 断言、page_source 文本断言或 screenshot 存在性断言
- 报告必须记录 trigger、scenario、lifecycle action、injection channel、ready anchors 和证据路径

### Help 命令手动 E2E 示例
- 用户要求“测试 Help 命令是否过时”时，运行：
  - `python scripts/agent_e2e.py --trigger manual --trigger-reason "test help freshness" --scenario test --command ':help' --expect-log-regex 'help|Help|帮助' --dump-after-command`
- 若运行时输出与当前命令能力不一致，修复 Help 生成路径或命令配置，再重跑相关脚本测试和本 E2E。

### OnFail
- 触发 `!dump`
- 如果证据指向可修复问题：修改代码/配置 → 重跑相关单元/脚本测试 → 重跑本 E2E
- 如果受设备、Appium、账号、selector、注入通道或期望行为缺失阻塞：报告 blocker、已收集证据和下一步用户动作
- 重复问题记录到 `agent/known_issues.md`；缺少输入记录到 `agent/questions.md`
