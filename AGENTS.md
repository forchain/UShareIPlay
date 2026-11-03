# AGENTS.md

UShareIPlay 是基于 Appium 的 Android 自动化服务（控制 Soul App 与 QQ 音乐）。

## 1. 核心开发与变更铁律 (Invariants)

- **Surgical Changes（最小改动）**：每行修改必须能直接追溯到用户诉求；严禁顺手格式化或重构未损坏的相邻代码；改动引起的孤立引用必须清理，已有死代码未经要求不得删除。
- **Goal-Driven Execution（目标驱动）**：定义明确可验证的成功标准（如测试用例或可观测输出），验证通过前严禁声称完成。
- **Logging Policy（日志静默）**：严禁在循环监控、轮询、周期性检测中输出无行为触发的日志。仅在触发具体行为（座位/用户变更、解析命令、进退房、弹窗交互、错误异常）时输出 INFO/CRITICAL 日志。
- **Local Element Overrides Policy（元素覆盖策略）**：允许在 `config.local.yaml` 中覆盖元素选择器（用于快速应对 App 定位符变更而免于重新发版）。加载时仅输出 WARNING 日志提醒尽快并入 `config.yaml`。
- **Direct Attribute Access（禁止动态属性反射）**：禁止通过 `getattr(obj, "attr", default)` 获取成员属性（如 `getattr(self.soul_handler, "config", None)`），确保静态类型可分析；仅在明确的动态多态或测试 mock 场景下例外。
- **Lean Code & Fail-Fast（精简代码与快速失败）**：保持代码精简，禁止防御性过度判空和无意义的异常吞咽，优先让错误及早暴露；多值条件或紧凑赋值优先使用三元条件表达式。
- **No Unsolicited Compatibility Shim（拒绝无要求兼容层/新机制彻底替换）**：引入新机制时，除用户明确要求兼容旧机制外，直接用新机制彻底替换旧机制。严禁擅自编写双轨兼容、双重回退或静默降级逻辑，确保代码精简，并保证新机制真实生效。
- **Early Return（提前返回减嵌套）**：减少代码嵌套层级，条件不满足时尽早 return / continue / break（Guard Clause）。
- **Just-In-Time Element Query（即用即查）**：Appium 元素对象必须在即将操作前实时定位获取，严禁提前长周期缓存 WebElement，避免因界面更新引发 StaleElementReference 或操作失效。
- **Two Name Domains（两个命名域）**：UI 呈现为可见昵称，DB 存储为 canonical 名。以用户名作为参数的 UI 操作必须经 `InfoManager.resolve_visible_username` 解析，详见 [docs/users.md](docs/users.md)。
- **Seat vs Mic Terminology（座位与麦位术语）**：房间 1~12 号位置统一称为「座位（Seat / 在座）」，开麦发言才称为「麦位（Mic / 上麦）」，文案与注释严禁混淆，详见 [GLOSSARY.md](GLOSSARY.md)。

## 2. GitHub 与 PR 工作流

### Branch Naming (铁律)
分支统一使用 `<type>/<slug>` 格式（斜杠分隔，严禁使用 `forchain/fix-<slug>` 等连字符格式）：
- 类型前缀：`fix/`、`feat/`、`chore/`、`refactor/`、`docs/`、`test/`
- slug 使用短横线小写，不重复类型前缀（如 `fix/seat-panel-collapse-race`）。

### GitHub Account Switching
创建或编辑 PR 时，`gh` 账号须与 `remote.origin.url` 匹配：
- 提取远程 URL 的用户名（如 `https://forchain@github.com/...` → `forchain`）；
- 使用 `gh auth switch -h github.com -u <remote-username>` 临时切换，操作完成后切回原账号。

## 3. 领域与架构文档指针 (Context Pointers)

需要深入对应模块时，查阅专门文档：
- **用户识别与权限体系**：查阅 [docs/users.md](docs/users.md) 与 [docs/adr/0008-role-hierarchy-and-operator-protection.md](docs/adr/0008-role-hierarchy-and-operator-protection.md)
- **配置系统与本地覆盖**：查阅 [docs/config.md](docs/config.md)
- **工作区与 Git Worktree 初始化**：查阅 [docs/worktree-init.md](docs/worktree-init.md)
- **房间与座位驱动机制**：查阅 [docs/room.md](docs/room.md) 及 [GLOSSARY.md](GLOSSARY.md)
- **Issue 管理与 Triage**：查阅 [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md) 与 [docs/agents/triage-labels.md](docs/agents/triage-labels.md)
