## 1. Async 事件循环安全（去阻塞）

- [x] 1.1 盘点在 asyncio 路径中使用的阻塞调用（至少覆盖 `EventManager` 未知页面兜底路径），列出清单与文件/行号
- [x] 1.2 将 asyncio 路径中的 `time.sleep(...)` 替换为 `await asyncio.sleep(...)`（优先修复连续未知页面退避处）
- [x] 1.3 为未知页面退避/节流补充“非阻塞且有上限”的实现细节（保持现有行为意图，但不冻结 loop）
- [x] 1.4 运行脚本级验证：确保修复后无语法错误（`python -m py_compile` 目标文件）并检查 `EventManager.process_events` 逻辑仍可执行

## 2. 命令解析结果隔离（避免配置污染）

- [x] 2.1 修改 `CommandParser.parse_command`：返回解析结果副本（包含 `parameters`）而不是写回共享命令配置对象
- [x] 2.2 审计 `CommandManager` 对 `command_info` 的消费点，确保使用的是“本次解析结果”而非依赖配置对象的可变字段
- [x] 2.3 增补一个最小回归脚本/测试：连续解析两条不同命令（或同一命令不同参数）时，后一次解析不受前一次影响（符合 specs 的场景）

## 3. Driver 恢复与重试策略收敛

- [x] 3.1 识别并分类当前使用 `@with_driver_recovery` 的方法：读操作（page_source/查询/读取属性）与写操作（点击/滑动/输入/发送）
- [x] 3.2 调整装饰器策略（参数化或拆分装饰器）：读操作恢复后允许自动重试一次；写操作默认不自动重试
- [x] 3.3 为关键决策点补充可观测性信号（日志或 `Observability.emit`）：发生恢复、发生自动重试、恢复成功但跳过重试
- [x] 3.4 运行现有脚本验证（至少 `python test_timer_restart.py`）确保改动不破坏 DB/timer 逻辑；对不需要设备的模块做 import/py_compile 验证

