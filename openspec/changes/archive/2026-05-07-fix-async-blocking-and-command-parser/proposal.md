## Why

当前运行时链路里存在几类“稳定性隐患”，会在高频消息/异常恢复/未知页面兜底时放大成停摆或隐蔽错：

- 异步事件循环路径中存在阻塞调用（例如 `time.sleep`），可能冻结 asyncio loop，导致定时器、消息队列与事件处理整体停顿。
- 命令解析阶段会把解析结果写回原始命令配置对象，造成配置污染；在并发/多来源注入（队列/控制台/Agent 注入）场景下，存在参数串台与不可复现 bug 风险。
- driver 失效恢复后对“有副作用”的 UI 操作自动重试，可能引发重复点击/重复提交等业务错，且难以通过日志快速定位。

## What Changes

- 将事件/兜底逻辑中的阻塞等待改为非阻塞（`await asyncio.sleep(...)`），避免卡住事件循环。
- 调整命令解析器，使其返回“解析结果副本”，不再修改/污染命令配置对象；保证每条消息解析的参数隔离。
- 收敛 driver 恢复后的自动重试策略：仅对幂等的只读动作自动重试；对写操作只做恢复与失败上抛/返回，由上层决定是否重试。

## Capabilities

### New Capabilities

- `async-event-loop-safety`: 运行时链路不得在 asyncio 事件循环中执行阻塞等待；未知页面退避/节流必须使用非阻塞机制。
- `driver-recovery-retry-policy`: 明确 driver 失效后的恢复与重试边界（读操作可自动重试，写操作默认不自动重试），并要求可观测（事件/日志可追踪）。

### Modified Capabilities

- `command-input-normalization`: 在“统一命令输入规范化”的能力上补充一条要求：命令解析结果不得污染全局命令配置，参数必须对每条输入隔离。

## Impact

- **代码影响面**：
  - `src/ushareiplay/managers/event_manager.py`（未知页面兜底与退避）
  - `src/ushareiplay/core/command_parser.py`（命令解析返回值语义）
  - `src/ushareiplay/core/driver_decorator.py` 以及相关 handler 调用点（恢复与重试策略）
- **行为影响**：
  - “连续未知页面”时不再冻结 loop；退避仍保留但不会阻塞其它协程。
  - 命令解析从“就地修改 config dict”变为“返回副本”，避免跨消息污染。
  - driver 恢复后对写操作不再自动重试，可能改变极少数依赖“自动重试成功”的隐式行为（需要在 tasks 里明确验收与回归点）。
