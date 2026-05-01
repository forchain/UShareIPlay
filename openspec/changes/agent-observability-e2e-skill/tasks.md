## 1. 基础输出目录与配置一致性

- [x] 1.1 新增统一的 artifacts 根目录约定（按 run_id 分桶），并提供路径解析工具函数
- [x] 1.2 修正 logger 配置读取：统一走 `ConfigLoader`（支持 `config.local.yaml` 覆盖）
- [x] 1.3 收敛默认日志目录到 workspace 内（保留可配置覆盖），避免 `../logs` 越界带来的权限问题

## 2. 结构化事件流（events.jsonl）

- [x] 2.1 新增事件写入器（JSONL）：核心字段 `schema_version/ts/level/event/run_id/ctx`，支持可选 `trace_id`
- [x] 2.2 在关键路径埋点：`app.start/app.stop`、`driver.init.*`、`driver.reinit.*`
- [x] 2.3 在队列链路埋点：`queue.enqueue`、`queue.drain.start`、`queue.drain.end`
- [x] 2.4 在命令链路埋点：`command.received`、`command.dispatch`、`command.result`（success/error）
- [x] 2.5 在状态链路埋点：`foreground.app`、`state.snapshot`、`state.ready`

## 3. 状态快照（status.json）与就绪判定

- [x] 3.1 定义 `status.json` schema 与版本号（schema_version），并实现写入（覆盖式更新）
- [x] 3.2 实现 anchors 探测（至少：`message_content`、`input_box_entry`、`input_box` 等）并写入快照
- [x] 3.3 实现 `foreground_app` 判定（基于 page_source packages）并写入快照
- [x] 3.4 实现 `CommandReady` 判定（与队列消费前提一致：message_content 可见为核心）
- [x] 3.5 将 `ui_lock`（locked/unlocked）与 `queue_size` 写入 `pipeline` 段

## 4. 只读证据产物导出（page source / screenshot）

- [x] 4.1 实现 run-scoped 证据产物落盘：`page_source.xml`、`screenshot.png`
- [x] 4.2 设计触发方式：失败自动触发（guard fail/assert fail），并记录事件 `artifact.*`
- [x] 4.3 增加一个内部后台命令（console/queue 路由）触发只读 dump（不引入外部 Appium session）

## 5. Agent Skill 资产（agent/ 目录）

- [x] 5.1 新增 `agent/capabilities.json`（硬规则：禁止外部 Appium session、输入走 console/queue、只读证据由主程序导出）
- [x] 5.2 新增 `agent/preconditions.md`（CommandReady/状态锚点/Guard 口径）
- [x] 5.3 新增 `agent/event_taxonomy.md`（最小断言集：enqueue→drain→dispatch→result）
- [x] 5.4 新增 `agent/playbooks/command_e2e.md`（Guard/Advance/Inject/Assert/OnFail）
- [x] 5.5 新增 `agent/playbooks/timer_e2e.md`（含 DB 加速策略与断言）
- [x] 5.6 新增 `agent/known_issues.md` 与 `agent/questions.md`（自我进化闭环）
- [x] 5.7 新增 `agent/fixtures/`：样例 `status.json` 与 `events.jsonl`（用于解析器自测）

## 6. E2E 冒烟测试（自动化）

- [x] 6.1 新增一个可运行的 E2E 冒烟脚本：启动服务 → 等待 ready 或进入无设备降级模式 → 注入命令 → 断言事件链路完整
- [x] 6.2 无设备降级策略：在无法连接 Appium/无设备时，仍验证 console/queue→command→events/status 的链路（不测试真实 UI）
- [x] 6.3 将 E2E 冒烟加入到 `tests/` 或独立脚本（与仓库现有“脚本式测试”风格一致）

## 7. E2E Runner 生命周期与后台注入（补充）

- [x] 7.1 在 `agent/` playbooks 中补充 Scenario/Lifecycle：`dev` 默认重启，`test` 优先复用健康进程
- [x] 7.2 为 runner 增加健康检查：managed PID、fresh `status.json`、fresh `events.jsonl`、CommandReady/可等待状态
- [x] 7.3 增加复用进程可用的后台命令注入通道（不依赖 runner 持有 stdin），并汇入现有 console/queue 路径
- [x] 7.4 修正 `scripts/agent_e2e.py`：`--scenario test` 复用已有进程时仍能注入命令；无法注入时给出明确 blocker，而不是走到后置失败
- [x] 7.5 扩展报告：记录 scenario、生命周期动作、注入通道、ready anchors、事件/日志/DB/UI 断言摘要
- [x] 7.6 增加日志断言参数（例如 expected log regex / recent log excerpt）并写入报告
- [x] 7.7 增加只读 UI 断言参数（page_source 文本/XML 查询、截图存在性，可选 OCR/image compare）并写入报告
- [x] 7.8 为 `dev` 重启、`test` 复用、`test` 未启动则启动、复用进程注入失败四条路径增加脚本式测试

## 8. 自动/手动触发与迭代闭环（补充）

- [x] 8.1 在 `agent/` playbooks 中补充 Trigger Policy：`auto` 与 `manual`
- [x] 8.2 为自动触发定义风险判断清单：命令、队列、定时器、DB、日志/事件、UI 反馈、Appium/ready、跨组件工作流
- [x] 8.3 为手动触发定义硬规则：必须启动或复用程序并通过后台/console/queue 注入真实命令，静态检查只能作为辅助证据
- [x] 8.4 为 runner 增加 `--trigger auto|manual` 参数，并在报告中记录
- [x] 8.5 扩展报告模板：记录自动触发原因或用户手动触发需求
- [x] 8.6 定义失败后的修复-重测循环：E2E 失败且可修复时修改代码，重新跑相关单元/脚本测试，再重新跑 E2E
- [x] 8.7 定义停止条件：设备/Appium/账号/selector/注入通道/期望行为缺失时输出 blocker、证据和下一步
- [x] 8.8 增加 Help 命令手动 E2E playbook 示例：运行程序 → 注入 `:help` → 验证运行时输出是否与当前命令能力一致 → 必要时修复并重测
