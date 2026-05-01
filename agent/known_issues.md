## 已知问题（会影响 E2E 或诊断）

### 1) logging.directory 为 `../logs` 时可能越界/权限错误
- 现象：日志目录不在 workspace 内，某些环境会 PermissionError 或无法采集
- 当前策略：自动收敛到 workspace 内的 `logs/`（仍允许配置覆盖，但越界会被纠正）

### 2) 队列不消费（看起来“命令没反应”）
- 根因：队列消费在 `MessageContentEvent` 的更新逻辑中；必须能触发 `message_content` anchor
- 诊断：查看 `status.json.anchors` 是否包含 `message_content`；必要时触发 `!dump` 收集 page_source

