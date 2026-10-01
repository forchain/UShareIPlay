## ADDED Requirements

### Requirement: UI animation waits in async command execution chains MUST be non-blocking
在 `async def` 命令或事件处理函数的调用链上，所有用于等待 UI 动画完成的延迟（如 `expand_seats` 后的等待、弹窗消失等待等）**MUST** 使用 `await asyncio.sleep()` 而非 `time.sleep()`。

#### Scenario: Seat expansion wait does not block timer tick
- **WHEN** 用户触发 seat 命令，`check_user_specific_seat()` 被 await，内部需要等待座位展开动画
- **THEN** 等待 MUST 通过 `await asyncio.sleep()` 实现
- **AND THEN** 在等待期间，事件循环 MUST 能推进 TimerManager 的 tick 和 MessageQueue drain

#### Scenario: Notice default setup wait does not block event loop
- **WHEN** `PostPartyCreateAutomation.on_command_ready()` 触发 `set_default_notice()` 设置 notice
- **THEN** 其中的 UI 稳定等待 MUST 通过 `await asyncio.sleep()` 实现
- **AND THEN** 等待期间其他协程（如消息队列 drain）MUST 不受阻塞

### Requirement: SeatUI animation methods invoked from async paths SHALL be async
`SeatUIManager` 中的 `expand_seats()` 和 `collapse_seats()` 方法在被 `async def` 方法调用时 **SHALL** 为 `async def`，以允许内部的动画等待非阻塞化。

#### Scenario: expand_seats called from async seat_check path
- **WHEN** `SeatCheckManager.check_user_specific_seat()` 调用 `seat_ui.expand_seats()`
- **THEN** `expand_seats` MUST 为 `async def` 并 `await asyncio.sleep()` 代替 `time.sleep()`
