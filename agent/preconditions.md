## 关键概念

### CommandReady（命令可测/队列可消化）

CommandReady 是端到端测试命令能力的硬门槛（Guard）。系统满足以下条件时视为 CommandReady：

- 前台应用为 **Soul**（由 `page_source` 的 package 判断）
- `anchors` 至少包含 `message_content`（因为队列消费发生在 `MessageContentEvent` 的更新路径）
- 建议同时包含 `input_box_entry` 或 `input_box`（佐证聊天框可操作）
- `pipeline.ui_lock == unlocked`

## 常用 Guard

- **测试聊天命令 `:xxx`**
  - requires: CommandReady

- **测试定时器链路**
  - requires: CommandReady
  - requires: DB 可访问（用于加速/断言）

