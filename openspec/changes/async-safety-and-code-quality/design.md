## Context

UShareIPlay 是一个 Python 异步自动化框架，主循环运行在 asyncio 事件循环上。`AppController.start_monitoring()` 是顶层 `async def`，它 await `EventManager.process_events()`，后者再 await 各 `BaseCommand.process()`，进而调用各 Manager 方法。

架构 review 发现：`seat_check.py`、`seating.py`、`seat_ui.py`、`notice_manager.py` 中的部分方法虽然被 `async def` 调用，但内部使用 `time.sleep()`，直接阻塞 asyncio 线程。全项目还有 55 处 `print()` 绕过了 logging 体系，以及 `scroll_container_until_element` 中 5 处重复的列表反转代码块。

`openspec/specs/async-event-loop-safety/spec.md` 已有规范要求不在 async 路径中阻塞，但此前只覆盖了 EventManager 的兜底退避路径，未覆盖命令执行链中的 manager 方法。

## Goals / Non-Goals

**Goals:**
- 将 `async def` 调用链上所有 `time.sleep()` 替换为 `await asyncio.sleep()`
- 将全项目 `print()` 统一改为 `self.logger.*()` 调用
- 提取 `_reversed_if_needed()` helper 消除 scroll 方法中的重复代码
- 将根目录 4 个 `test_*.py` 移至 `tests/`
- 清理 `_init_handlers` 中冗余的重复 import

**Non-Goals:**
- 不重构 `AppHandler` 为多个 mixin 模块（风险/收益比不合算）
- 不引入 ServiceRegistry（过度设计）
- 不改动同步方法（如 `_start_apps`、`reinitialize_driver`）中的 sleep，这些在初始化阶段阻塞是可接受的
- 不拆分 `config.yaml`（单独 change 处理）
- 不引入新依赖

## Decisions

### 决策 1：只修复 async 调用链上的 sleep，不全量替换

**选择**：只替换在 `async def` 调用链上的 `time.sleep()`，保留初始化阶段（`_start_apps`、`reinitialize_driver`）和纯同步辅助方法中的 sleep。

**理由**：
- 初始化阶段本身是在 `asyncio.run()` 前或 `sync` 上下文中执行，阻塞可接受
- 全量替换会引入 `async def` 传染效应，需要大量重构继承链
- 精准替换风险最低，收益最明确

**替代方案考虑**：用 `asyncio.to_thread(lambda: time.sleep(n))` 包裹同步 sleep——但这只是把问题包装了一层，不如直接用 `await asyncio.sleep(n)` 清晰。

**需要替换的具体位置**：
```
seat_check.py:75   → await asyncio.sleep(0.5)  # check_user_specific_seat (async def)
seat_check.py:115  → await asyncio.sleep(0.5)  # check_user_specific_seat (async def)
seat_check.py:150  → await asyncio.sleep(1)    # _handle_occupied_seat (async def)
seating.py:34      → await asyncio.sleep(0.5)  # reserve_seat → check_seats_on_entry 链
seating.py:75      → await asyncio.sleep(0.5)  # take_seat 链
seating.py:169     → await asyncio.sleep(0.5)  # _check_seat_occupant (async def)
seating.py:232,237 → await asyncio.sleep(0.3)  # _handle_occupied_seat (async def)
seat_ui.py:78,117  → 保留（SeatUIManager 方法为同步，由 async 方法同步调用）*
notice_manager.py:229 → await asyncio.sleep(3) # set_default_notice，被 PostPartyCreateAutomation async 路径调用
```

> *`seat_ui.py` 中的 sleep 在同步方法中，但通过 `expand_seats()` 被 `async def` 调用。需要将 `expand_seats()` 改为 `async def` 并添加 `await asyncio.sleep()`，或抽出 inline 到调用方。倾向于将 `seat_ui.py` 的 expand/collapse 改为 `async def`，由 `seat_check` 和 `seating` await。

### 决策 2：print → logger 的替换策略

**选择**：在 `__init__` 或构造阶段无 logger 时，保留少量 print 作为 bootstrap 输出；其余全部改为 `self.logger.*()` 调用。

**映射规则**：
- 启动信息 → `logger.info()`
- 错误/异常 → `logger.error()`
- 调试细节 → `logger.debug()`
- `AppController.__init__` 中 bootstrap 前的 print → 保留（logger 尚未建立）

### 决策 3：scroll helper 提取方式

**选择**：在 `AppHandler` 类内提取 `_reversed_if_needed(lst, direction)` 私有方法，5 处调用点改为调用该方法并直接 return。

```python
def _reversed_if_needed(self, lst: list, direction: str) -> list:
    """Return list reversed if direction is 'down' or 'right'."""
    return list(reversed(lst)) if direction in ("down", "right") else lst
```

这比提取到外部模块更保守，且不改变公共 API。

### 决策 4：测试文件移动策略

将 `test_avatar_exit.py`、`test_command_parser_no_config_mutation.py`、`test_keyword_acl.py`、`test_user_canonical_mapping.py` 直接移至 `tests/`，保留文件内容不变。检查 pyproject.toml 的 `testpaths` 配置，确认 pytest 能自动发现。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|---|---|
| `seat_ui.py` 的 `expand_seats()` 改为 async 后，如有其他同步调用方会编译报错 | 改动前 `grep -rn "expand_seats\|collapse_seats"` 全量确认调用点 |
| `notice_manager.set_default_notice()` 改为 async 后，需要同步更新调用方 | 改动前 `grep -rn "set_default_notice"` 确认调用链 |
| print 替换遗漏导致部分日志丢失 | 用 `grep -rn "print(" src/` 验证，PR 前复查 diff |
| 测试文件移动后 CI 路径失效 | 移动后立即运行 `uv run pytest -q` 验证 |
