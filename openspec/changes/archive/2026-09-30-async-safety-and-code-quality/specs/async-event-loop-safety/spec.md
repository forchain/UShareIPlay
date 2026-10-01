## MODIFIED Requirements

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
