## Purpose
Ensure runtime operations executed in the asyncio event loop do not use blocking waits, keeping the event loop responsive.

## Requirements

### Requirement: No blocking waits in asyncio execution paths
运行时在 asyncio 事件循环上下文中执行的逻辑（包括事件处理、未知页面兜底、退避/节流、定时器调度、消息队列 drain，**以及命令执行链中调用的 manager/UI 操作方法**）**MUST NOT** 使用阻塞等待（例如 `time.sleep(...)` 或其它会阻塞线程的长等待）。

#### Scenario: Unknown page backoff does not freeze the event loop
- **WHEN** 系统进入"连续未知页面"兜底路径并触发退避/等待
- **THEN** 退避/等待 MUST 通过非阻塞方式实现（例如 `await asyncio.sleep(...)`）
- **AND THEN** 在退避期间，事件循环 MUST 仍能推进其它协程（例如 timer tick、消息队列 drain、命令分发/结果回写）

#### Scenario: Command execution does not freeze the event loop during UI waits
- **WHEN** 用户命令（如 `:seat`、`:notice`）触发需要 UI 动画等待的操作
- **THEN** 所有等待 MUST 通过 `await asyncio.sleep()` 实现
- **AND THEN** 在等待期间，事件循环 MUST 仍能推进 timer tick 和消息队列 drain

### Requirement: Backoff logic SHALL be cooperative and bounded
未知页面兜底的退避/节流逻辑 **SHALL** 以“协作式”的方式让出事件循环时间片，并且 MUST 具备可控上限（不得无限增长导致系统长期不可用）。

#### Scenario: Backoff remains bounded
- **WHEN** 系统连续多轮进入未知页面兜底路径
- **THEN** 退避时长 MUST 处于预先定义的上限范围内（例如不超过固定阈值）
- **AND THEN** 退避完成后系统 MUST 继续进入下一轮检测/恢复流程
