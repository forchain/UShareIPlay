## Why

当前项目的运行信息主要依赖人类可读的日志与 `print(...)`，缺少稳定的结构化事件流与统一的状态快照，导致 Agent 难以在不接触 UI（避免二次 Appium session 冲突）的前提下做可靠的端到端验证与失败归因。现在需要把“可测试状态/证据链/报告产出”变成一等公民，让未来功能迭代的 E2E 自动化越来越高效。

## What Changes

- 新增面向 Agent 的**可观测性输出**：结构化事件流（JSONL）、状态快照（JSON）、失败时只读证据产物（page source / screenshot），形成可回放的证据链。
- 统一并收敛日志与输出策略：减少关键路径 `print(...)` 丢失上下文；让 logger 配置读取与 `ConfigLoader` 保持一致；避免 `../logs` 等越界路径导致的权限与采集问题。
- 引入“测试就绪”判定与状态锚点（anchors）概念：将 `InChatReady` 等关键状态显式化，作为命令测试与队列消费的硬前置条件（Guard）。
- 增加可自我进化的 Agent Skill 资产：能力登记册（capabilities）、前置条件（preconditions）、事件字典（taxonomy）、场景剧本（playbooks）、已知问题与问询模板，支持在协作中持续沉淀与改进。
- 提供一个最小可运行的 E2E 冒烟验证脚本/流程：按场景决定复用或重启服务 → 等待就绪（或降级到无设备模式验证链路）→ 通过后台控制通道/console/queue 注入命令 → 用事件/状态/日志/DB/UI 证据断言成功。
- 新增 Agent E2E runner 的进程生命周期策略：开发场景默认停止旧进程并重启；测试场景优先复用健康的已运行进程，只有未启动或不健康时才启动。
- 新增可复用进程的后台注入通道要求，避免 runner 只有在自己启动子进程时才能写 stdin，导致无法对既有运行实例执行端到端测试。
- 支持自动与手动两种触发方式：自动触发用于单元测试通过后仍存在端到端风险的功能验证；手动触发用于用户明确要求验证某个真实运行行为。
- 将 E2E 从“一次性检查”提升为闭环：失败时 Agent 应基于证据修复代码并重新执行必要测试，直到通过或明确需要用户帮助。

## Capabilities

### New Capabilities

- `agent-observability-events`: 统一输出结构化事件流（JSONL），包含 `run_id/trace_id/event/ctx`，覆盖状态变化、队列消费、命令分发与结果、证据产物产出等关键点。
- `agent-state-snapshot`: 统一输出版本化的 `status.json`（schema 可演进），用于判定前台 App、Soul/QQMusic 状态、anchors、`ui_lock`、队列大小、party_id、timers/播放信息摘要等。
- `agent-artifacts-dump-readonly`: 通过主程序现有 Appium session 生成只读证据产物（page_source.xml、screenshot.png），在 guard fail / assert fail 时落盘并在事件中引用路径；外部 Agent 不创建新 session。
- `agent-e2e-skill-assets`: 在仓库内新增 `agent/` 资产目录（capabilities/preconditions/taxonomy/playbooks/known_issues/questions/fixtures），让 Skill 能力与前置条件可版本化、自我进化。
- `agent-e2e-runner-lifecycle`: 定义 Agent E2E runner 的场景识别、进程发现、复用/重启决策、后台命令注入、日志/DB/UI 证据采集与报告要求。
- `agent-e2e-trigger-policy`: 定义 Agent 何时自动运行 E2E、如何响应用户手动触发、以及失败后的迭代闭环。

### Modified Capabilities

- `agent-docs-system`: 扩展并制度化“Agent 端到端测试/证据链/自我进化资产”的文档与约束（尤其是禁止外部 Appium session 的硬规则与就绪判定口径）。

## Impact

- **核心运行链路**：`src/ushareiplay/core/app_controller.py`、`src/ushareiplay/managers/event_manager.py`、`src/ushareiplay/events/message_content.py`（队列消费与就绪锚点）、命令分发链路（`CommandManager`）。
- **日志体系**：`src/ushareiplay/core/app_handler.py`、`src/ushareiplay/managers/message_manager.py`（chat logger），以及 `config.yaml` 的 logging 配置读取一致性与默认路径策略。
- **新增资产与脚本**：新增 `agent/` 目录与示例 fixtures；新增/更新 E2E 冒烟脚本（需支持“无设备降级”以便 CI/云环境验证）。
