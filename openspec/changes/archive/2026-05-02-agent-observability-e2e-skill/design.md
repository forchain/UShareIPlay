## Context

该项目是基于 Appium 的安卓自动化程序，主程序在启动时创建并持有唯一的 Appium session（driver），同时操作 Soul 与 QQ 音乐两款 App。为了避免 session 冲突，外部 Agent/Skill **禁止**再创建第二个 Appium session 进行 UI 操作；允许的 Appium 能力仅限于由主程序现有 session 执行的**只读证据导出**（page source、截图）。

当前可观测性现状存在以下问题：

- 日志输出混杂：大量关键路径使用 `print(...)`，不会进入文件日志，且不利于机器聚合。
- logger 配置读取绕过 `ConfigLoader`，直接读取 `config.yaml`，会忽略 `config.local.yaml` 覆盖；`logging.directory` 默认为 `../logs` 这类越界相对路径，容易导致权限与采集问题。
- 缺少结构化事件流与统一状态快照，Agent 无法可靠地判断“就绪状态（如 InChatReady）”，也难以形成可回放的端到端证据链。
- 队列消费与命令执行的隐式前置条件未显式化：异步队列在 `MessageContentEvent` 触发的更新逻辑中被消化，因此“聊天列表可见/事件触发”是命令类 E2E 的硬门槛。

约束与原则：

- 外部 Agent/Skill 不触碰 UI（不触屏、不按键、不切 App），输入统一通过 console/queue 注入。
- 状态判定尽可能基于 `page_source`（一次性获取、可解析、可落盘）与现有事件系统（EventManager）。

## Goals / Non-Goals

**Goals:**

- 提供可机器解析、可回放、可聚合的**结构化事件流**（JSONL），覆盖：
  - 前台 App 与关键状态变化
  - 队列入队/出队/消费统计
  - 命令分发与结果（含 trace_id）
  - 只读证据产物（page_source、截图）的生成与路径引用
- 提供版本化 `status.json` 状态快照（schema 可演进），让 Skill 能在“只读 + console 注入”约束下做 Guard/Advance/Assert。
- 统一日志与输出策略：日志目录解析走 `ConfigLoader`，并默认收敛到 workspace 内；减少关键路径 `print(...)` 丢失上下文。
- 在仓库中新增 `agent/` 资产（capabilities / preconditions / taxonomy / playbooks / known_issues / questions / fixtures），让 Skill 具备“自我进化”的可版本化载体。
- 提供最小 E2E 冒烟测试：启动服务（可无设备降级）→ 等待就绪或验证链路 → 注入命令 → 用事件/状态/DB 断言成功。

**Non-Goals:**

- 不引入外部 Agent 直接连接 Appium driver 的能力；不允许创建第二个 session。
- 不把所有业务行为都改造成“完全结构化”的领域事件；优先覆盖 E2E 与诊断所需的关键路径。
- 不在本次变更内完成大规模 UI selector 体系重构（config.yaml 仍是权威来源）。

## Decisions

### 1) 以 JSONL 作为结构化事件流（events.jsonl）

**Decision:** 新增统一的事件写入器，输出 `events.jsonl`（一行一个 JSON 对象）。

**Rationale:**

- JSONL 适合流式追加、崩溃恢复、与后续报告/聚合工具兼容。
- 与当前 logger 并存：人类可读日志仍保留；机器断言优先使用 events.jsonl。

**Alternatives considered:**

- 仅使用现有文本日志：解析脆弱、语义混用、难以建立 trace_id。
- 单一大 JSON：不利于流式追加与崩溃时部分写入。

### 2) 输出版本化状态快照（status.json），以 anchors 推断“就绪”

**Decision:** 主程序周期性/关键节点输出 `status.json`，包含 `schema_version`、`run_id`、前台 App、Soul/QQMusic 状态、anchors、`ui_lock`、队列大小、party_id、timers/播放信息摘要等。

**Rationale:**

- Skill 的 Guard/Advance 需要一个稳定的“状态面板”，避免靠 log 文本猜测。
- `InChatReady` 的判定应以 anchors（如 `message_content`、`input_box_entry`）为硬指标，且与队列消费路径一致。

**Alternatives considered:**

- 仅靠 events 回放推断当前状态：可行但成本更高；status.json 可作为低成本缓存与快速入口。

### 3) 只读证据产物必须由主程序现有 session 生成并落盘

**Decision:** 定义 “artifact dump” 机制：在 guard fail / assert fail / 关键诊断点，由主程序 driver 导出：

- `page_source.xml`
- `screenshot.png`

并在事件中写入 `artifact_path`。

**Rationale:**

- 满足“外部 Agent 不创建第二个 session”的硬约束。
- 证据落盘后，Skill 只需读文件即可诊断与生成报告。

**Alternatives considered:**

- Agent 直接调用 Appium：会与主 session 冲突，禁止。
- 仅保存日志：对于 UI 场景不够，缺乏可复核证据。

### 4) 输入通道标准化：console/queue 注入 + trace_id 贯穿

**Decision:** E2E 测试输入统一走 console/queue；为每次测试注入生成 `trace_id`（可由 Skill 生成并写入命令前缀/元数据，或由主程序在入队时分配），并贯穿：

- `queue.enqueue` → `queue.drain.*` → `command.dispatch` → `command.result`

**Rationale:**

- 与现有队列消费机制一致，避免 UI 冲突。
- trace_id 能让失败归因与报告聚合可靠。

### 5) Skill 的“自我进化”通过仓库资产实现（agent/）

**Decision:** 新增 `agent/` 目录保存：

- `capabilities.json`：能力登记册与硬规则（尤其是禁止外部 Appium session）
- `preconditions.md`：就绪判定与 Guard 定义
- `event_taxonomy.md`：事件字典与断言最小集
- `playbooks/`：场景剧本（command/timer/music/recovery 等）
- `known_issues.md`：不可修/暂不修与下次所需补充信息
- `questions.md`：标准化问询模板
- `fixtures/`：样例 status/events

**Rationale:**

- 避免依赖隐式记忆；让协作中的新经验可被版本化、可 review、可迭代。

### 6) E2E runner 必须把“生命周期”和“注入通道”作为一等能力

**Decision:** Runner 按场景选择进程生命周期：

- `dev`：默认停止旧的 managed process 并重新启动，确保测试的是最新代码。
- `test`：优先复用健康的已运行进程；只有进程不存在、不健康、或 artifacts 过期时才启动。

复用进程时，命令注入不能依赖当前 runner 拥有子进程 stdin；系统需要一个可复用的后台注入通道（例如文件 spool、本地 IPC 或 socket），并且该通道必须汇入同一条 console/queue 路径。

**Rationale:**

- 只靠 `subprocess.Popen(stdin=PIPE)` 可以测试 runner 自己启动的进程，但无法对已经运行的应用做真正的端到端复用测试。
- 用户区分了“刚开发完需要重启”和“只是测试现有功能尽量复用”的两种工作流；如果生命周期策略不显式化，Agent 会在不同任务中做出不一致选择。

**Alternatives considered:**

- 每次都 kill/restart：开发场景简单可靠，但测试场景会破坏真实运行状态，不符合端到端验证意图。
- 永远复用：无法保证代码变更后的测试覆盖新代码，也会受旧状态污染。
- 直接附加到现有 stdin：不可移植且通常不可行；后台控制通道更稳定。

### 7) 验证结果应形成多源证据链

**Decision:** Runner 报告至少支持事件、状态、日志、DB、只读 UI 证据五类断言；UI 断言只能读取主程序导出的 `page_source.xml` / `screenshot.png`，可选使用 XML 解析、OCR、图像匹配等开源工具分析文件。

**Rationale:**

- 单看 `command.result` 不足以证明用户可见反馈正确。
- 日志和 DB 能覆盖内部副作用；截图/page_source 能覆盖 UI 反馈；事件/trace_id 用来串起一次测试动作。

### 8) Skill 支持自动触发与手动触发

**Decision:** E2E skill/runner 有两种入口：

- 自动触发：Agent 完成功能或修复后，单元/脚本测试已经通过，但变更涉及命令链路、队列、定时器、DB 副作用、日志输出、状态快照、UI 可见反馈、Appium 交互或用户工作流时，Agent 可以自主运行 E2E。
- 手动触发：用户明确要求“测试某个功能/命令/现象”时，Agent 必须按真实运行路径启动或复用服务、注入命令、采集证据并判断结果。

手动触发不能退化成静态检查。例如“测试 Help 命令是否过时”必须通过运行程序并输入 Help 命令观察产物；读取 config 只能作为辅助对照，不能替代端到端验证。

**Rationale:**

- 单元测试通过只能证明局部逻辑正确；端到端风险通常来自启动、配置、队列消费、异步事件、数据库、日志和 UI 反馈组合。
- 用户手动怀疑一个功能时，目标是验证真实行为，不是证明源文件看起来一致。

### 9) E2E 是可迭代闭环，不是单次报告

**Decision:** 当 E2E 失败且证据指向可修复的代码/配置问题时，Agent 应回到实现流程修复，然后重新运行相关单元测试和 E2E。只有在设备/账号/选择器/环境/需求信息缺失等无法自行推进时，才停止并向用户给出 blocker 和已收集证据。

**Rationale:**

- 端到端测试的价值在于把功能推进到真实可用；只报告失败但不尝试修复，会把工作停在诊断阶段。
- 明确 blocker 能避免 Agent 在缺少设备状态或用户决策时反复无效重试。

## Risks / Trade-offs

- **[Risk] 事件/状态输出带来性能开销** → Mitigation：仅输出关键字段；事件写入采用追加写；page_source/截图仅在失败或显式诊断触发时落盘。
- **[Risk] status.json/事件字段演进导致兼容问题** → Mitigation：引入 `schema_version`；新增字段保持可选；提供 fixtures 与简单解析器自测。
- **[Risk] “就绪”判定在不同机型/版本上 anchor 不稳定** → Mitigation：anchors 采用多条件（message_content + input_box*）；失败时落盘 page_source/screenshot 以便快速补 selector；将“缺 selector”前置为 questions 模板。
- **[Risk] 现有 logger 路径越界/权限问题影响采集** → Mitigation：日志路径解析统一走 ConfigLoader，并默认收敛到 workspace 内（允许 config.local.yaml 覆盖）。
- **[Trade-off] 不允许外部 UI 操作会降低某些场景自动化能力** → Mitigation：通过后台命令/DB 加速/只读证据导出，优先覆盖高价值的命令链路与定时器链路。
