## Tasks

- [x] 配置层
  - [x] 在 `config.yaml` 的 `soul:` 下新增 `post_party_create`（enabled / wait_for_command_ready / commands）
  - [x] 明确默认值与空列表行为（no-op）

- [x] 事件与门闩（latch）组件
  - [x] 新增轻量自动化组件（例如 `PostPartyCreateAutomation`）
  - [x] 实现 `party.created(new)` 与 `CommandReady` 的 AND+once 逻辑
  - [x] 仅对“新建派对成功”触发一次（不覆盖恢复/重连）

- [x] 挂点集成
  - [x] 在 `PartyManager` 新建成功点发出 `on_party_created_new()`（或 emit 事件）
  - [x] 在 `AppController` 检测到 CommandReady 时调用 `on_command_ready()`
  - [x] 满足条件后把 `commands[]` 逐条投递到 `MessageQueue`（nickname 使用 `Console`）

- [x] 观测与日志
  - [x] 为 latch 状态变化与命令投递增加低噪音日志
  - [x]（可选）通过现有 `obs.emit` 增加一个 `automation.post_party_create.fired` 事件

- [x] 测试与最小回归
  - [x] 为 latch 行为新增一个不依赖设备的单测（建议：构造假 queue，断言投递次数与顺序）
  - [x] 跑 `uv run -m pytest -q tests/test_imports.py`

