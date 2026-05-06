## Why

当前系统在“新建派对成功”后会**自动就座并直接投递 `:radio`**（通过 `MessageQueue`），但这一行为是写死在代码中的，且不具备“等待聊天输入就绪（CommandReady）”的门控：

- 运营/使用上很难按不同场景启用/关闭或调整自动执行命令
- UI 时序波动时（创建流程结束仍停留在弹窗/设置页），过早投递命令可能失败或被延后处理，行为不可控

因此需要把“新建派对成功后的自动命令”抽象成一个**可配置的自动化 hook**：在建房成功后，等待系统判定“已在 Soul 聊天页且可输入命令”，再批量投递配置的命令列表。

## What Changes

- 新增配置项 `soul.post_party_create`，用于描述：
  - 是否启用该自动化
  - 是否需要等待 `CommandReady`
  - 需要自动投递的命令字符串列表（例如 `:radio sleep`、`:seat`）
- 新增一个轻量编排逻辑（latch/门闩）：
  - 仅在“新建派对成功”事件触发一次
  - 同时满足 `party.created(new)` 与 `CommandReady` 后执行一次性动作：按序投递 `commands[]` 到 `MessageQueue`

## Capabilities

### New Capabilities

- `post-party-create-commands`: 新建派对成功后，按配置自动投递命令列表
- `command-ready-gated-automation`: 以 `CommandReady` 为门控，避免过早执行

### Modified Capabilities

- `party-create-flow-hook`: 派对创建流程在成功点发出“新建派对成功”信号供自动化消费（不改变创建本身行为）

## Non-Goals

- 不引入通用工作流/规则引擎（只做单一 hook，避免过度抽象）
- 不支持在配置中直接调用内部函数（动作严格限定为“命令字符串 → MessageQueue”）
- 不把该 hook 扩展到“恢复派对/重连回房间/进入已有房间”（仅新建成功触发一次）
- 不在本变更中重构 `PartyManager` 的就座逻辑（是否配置化后续再议）

## Acceptance Criteria

- 当 `soul.post_party_create.enabled=false`：
  - 新建派对成功后不会自动投递任何命令
- 当 `enabled=true` 且 `wait_for_command_ready=true`：
  - 新建派对成功后，只有在系统进入 `CommandReady`（Soul 前台且聊天输入就绪）后才会投递 `commands[]`
  - `CommandReady` 先到或后到都能正确触发（具备门闩语义）
  - 同一次“新建派对成功”只触发一次，不会因后续重复 `CommandReady` 事件而重复投递
- 当 `enabled=true` 且 `wait_for_command_ready=false`：
  - 新建派对成功后立即按序投递 `commands[]`（用于排障/回退）

