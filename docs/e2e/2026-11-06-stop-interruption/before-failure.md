# Before（现场失败模式）

用户现场：`!stop` 触发的管理性 `asyncio.CancelledError` 从 `start_monitoring` 逃出 `asyncio.run`，进程退出；QQ Music 同步 Appium 编排无法被即时中断。

```text
asyncio.CancelledError: UI session 'state:scrape_online_users' blocked: runtime paused by !stop

  ... escapes start_monitoring → asyncio.run → process exit
  log ends with: Timer manager stopped

Also: QQ Music sync UI waits keep running until completion;
!stop only takes effect after the blocking Appium call returns.
```

对比 After：见 `after-log-excerpt.txt`（托管 PID 65085 全程存活、无 traceback）。
