## Capability: command-input-normalization

统一命令输入的空白与冒号兼容策略，确保所有入口（聊天、队列、定时器、关键字、enter/exit/return、控制台、Agent 注入）在命令识别与解析上表现一致。

### Definitions

- **Trigger colon**：命令触发符，允许 `:`（半角）与 `：`（全角）
- **Raw**：入口原始文本（可能包含行首空白、`说：` 片段、冒号前后空白）
- **Normalized**：去掉触发符并去掉前导空白后的内容（用于 prefix 匹配与参数解析）

## ADDED Requirements

### Requirement: Normalize command candidates across all injection paths

The system **MUST** normalize command-candidate text consistently across all entry points, to tolerate common novice whitespace patterns (leading whitespace, whitespace after the colon).

#### Scenario: Queue/Timer/Keyword/EnterExitReturn inputs with whitespace

Given 命令候选 raw 为下列任意一种：

- `:help`
- `: help`
- `： help`
- `  : help`
- `  ：  help`

When 系统对 raw 做规范化并交给命令解析器进行 prefix 匹配与参数解析  
Then 规范化结果 Normalized 必须等价于 `help`（即无冒号、无前导空白）  
And 命令解析器必须能识别该命令（与无空白输入一致）

#### Scenario: Empty command after colon should not execute

Given raw 为下列任意一种：

- `:`
- `:   `
- `：`
- `：   `

When 系统对 raw 做规范化  
Then 系统必须判定该条不应触发命令执行（不进入命令解析/分发）

### Requirement: Chat extraction supports whitespace after "说：" and fullwidth colon

The chat ingestion path **MUST** accept whitespace after `说：`, accept both `:` and `：`, and accept whitespace after the colon; extracted content **MUST** align with the normalization rules.

#### Scenario: Chat message command detection

Given 聊天 UI 文本（简化示例）为下列任意一种：

- `souler[张三]说：:help`
- `souler[张三]说： :help`
- `souler[张三]说：：help`
- `souler[张三]说： ： help`

When 系统检测该消息是否包含命令触发（`说：` 后出现 `:`/`：`）  
Then 必须判定为“命令消息”，进入命令处理链路

#### Scenario: Chat extraction yields consistent normalized content

Given 聊天 UI 文本为 `souler[张三]说： ： help`  
When 系统提取命令文本并执行统一规范化  
Then Normalized 必须等价于 `help`


