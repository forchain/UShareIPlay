## ADDED Requirements

### Requirement: Driver recovery SHALL be separated from retry policy
当 driver 会话失效（例如 InvalidSessionId / WebDriverException）时，系统 **SHALL** 先执行 driver 恢复（重建/重连）再决定是否重试原操作；恢复与重试 MUST 由明确的策略控制，而不是无差别自动重试。

#### Scenario: Recovery happens before any retry decision
- **WHEN** 任意被保护的方法捕获到 driver 失效异常
- **THEN** 系统 MUST 先尝试 driver 恢复流程
- **AND THEN** 仅在恢复成功后，才进入“是否重试”的策略判断

### Requirement: Read operations MAY auto-retry once after successful recovery
对幂等的只读操作（例如读取 `page_source`、查询元素存在性、读取属性等），在恢复成功后系统 **MAY** 自动重试一次，以提高稳定性与减少上层噪声。

#### Scenario: Read operation retries once after recovery
- **WHEN** 一个被标记为“读操作”的方法在恢复前失败于 driver 失效异常
- **THEN** 在恢复成功后系统 MAY 自动重试该方法一次
- **AND THEN** 若重试仍失败，系统 MUST 将失败信号返回给上层（不得无限重试）

### Requirement: Write operations MUST NOT auto-retry by default
对有副作用的写操作（例如点击、滑动、输入、发送消息、触发 activity 跳转等），在恢复成功后系统 **MUST NOT** 默认自动重试，以避免重复副作用；是否重试必须由上层显式决定或通过显式策略开启。

#### Scenario: Write operation does not retry automatically
- **WHEN** 一个被标记为“写操作”的方法在恢复前失败于 driver 失效异常
- **THEN** 在恢复成功后系统 MUST NOT 自动重试该方法
- **AND THEN** 系统 MUST 返回明确的失败信号（例如 None/False/异常），使上层能够决定下一步动作

### Requirement: Recovery and retry decisions MUST be observable
driver 恢复过程与“是否重试”的决策 **MUST** 具备可观测性（通过日志或结构化事件），便于排查偶现问题与回归验证。

#### Scenario: Observability records retry/no-retry decisions
- **WHEN** 恢复成功并发生一次自动重试
- **THEN** 系统 MUST 记录“recovery.retry”的可观测信号（含操作类型/方法名等最小上下文）
- **WHEN** 恢复成功但策略决定不自动重试
- **THEN** 系统 MUST 记录“recovery.no_retry”的可观测信号

