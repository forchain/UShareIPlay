## Overview

目标是让所有命令入口对以下输入表现一致：

- 行首空白：`"  : help"`
- `说：` 后空白：`"说： : help"`
- 全角冒号：`"：help"`
- 冒号后空白：`": help"` / `"：  help"`

核心思路：把“命令字符串规范化”做成一个清晰、可复用的步骤，并确保它发生在**统一入口**（命令执行前），同时对聊天侧“命令检测/提取”做同等的宽容匹配，避免入口行为分裂。

## Current State (key constraints)

### 命令执行链路（统一入口）

所有命令最终进入 `CommandManager.handle_message_commands(messages)`，其中会去掉开头的 `:`/`：`，然后调用 `CommandParser.is_valid_command()` 以 `startswith(prefix)` 判断，并用 `split()` 解析参数。

问题点：

- 去掉冒号后，如果字符串以空格开头（例如 `": help"` → `" help"`），`startswith(prefix)` 会失败，导致命令不被识别。

### 聊天侧命令检测/提取（入口不一致风险）

聊天侧目前用正则 `说：(:.+)`：

- 不支持全角冒号 `：`
- 不支持 `说：` 后空格再冒号（`说： :help`）

这会造成“队列/控制台能用，聊天不能用”的不一致。

## Proposed Design

### 1) Command normalization

定义规范化语义（实现上可为纯函数/方法；此处只定义行为）：

**Input**: 原始字符串 `raw`  
**Output**: `(is_command, cleaned)` 其中 `cleaned` 是喂给解析器的“无冒号、无前导空白”的命令文本。

规则：

1. `raw_l = raw.lstrip()`（允许行首空白）
2. 如果 `raw_l` 以 `:` 或 `：` 开头：
   - `after = raw_l[1:]`
   - `cleaned = after.lstrip()`（允许冒号后空白）
   - 若 `cleaned` 为空：`is_command = False`
   - 否则：`is_command = True`
3. 否则：`is_command = False`（该条不是命令，按普通消息处理）

落点策略：

- **主入口**：在 `CommandManager.handle_message_commands()` 中，对每条 `MessageInfo.content` 做规范化后再传入 `CommandParser`。
- **解析器兜底**：`CommandParser.is_valid_command()` / `parse_command()` 内部也对输入做 `lstrip()`（防止未来新增入口漏清洗）。

### 2) Chat command detection & extraction

聊天侧应使用与上面一致的容错语义：

- `说：` 后允许空白，再允许 `:`/`：`，再允许空白，然后才是命令内容。

建议的匹配语义（检测用）：

- `说：\s*[:：]\s*\S`（避免 `说： :   ` 空命令误触发）

提取语义（拿到命令文本）：

- 捕获 `说：\s*[:：]\s*(.+)` 的 group(1)，然后交由“命令规范化”统一处理（或直接当作 cleaned 的候选并 `strip()`）。

### 3) Console / Agent injection

控制台与 Agent 注入入口不应要求冒号必须是字符串第一个字符；应支持行首空白：

- 先 `lstrip()` 再判断是否 `:`/`：`
- 或正则等价于：`^\s*[:：]\s*\S`

保持注入链路仍走队列（`MessageQueue`）以复用相同消费/执行逻辑。

## Edge Cases & Decisions

- **仅兼容空白**：只扩展空白容错，不改变“必须有冒号”这一触发规则。
- **空命令**：`":"`、`":   "`、`"说： :   "` 不应触发命令执行（视作普通消息或忽略）。
- **误触发风险**：更宽的聊天匹配可能会把少量“以冒号开头的普通对话”当命令；但这是协议本身的成本，且通过 `\S` 限制可减少无意义触发。

## Observability / Debuggability

建议在命令接收事件中补充两个字段（如果已有事件体系则沿用）：

- `raw`: 原始输入（含冒号/空白）
- `normalized`: 规范化后的输入（无冒号、无前导空白）

用于快速定位“命令没触发到底是入口没识别、还是解析器不匹配”。

