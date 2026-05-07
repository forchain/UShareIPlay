## Why

架构 review 发现三类高价值、低风险的问题：（1）部分 `async def` 方法内仍使用 `time.sleep()`，直接阻塞 asyncio 事件循环，违反已有的 `async-event-loop-safety` spec；（2）全项目混用 `print()` 与 `logging`，导致运行日志不完整；（3）`AppHandler` 中的 `scroll_container_until_element` 存在 5 处重复的列表反转逻辑，以及散落在项目根目录的 4 个测试文件破坏了测试组织规范。现在处理这些问题成本最低，拖延后会随代码规模增长而变得更复杂。

## What Changes

- **修复 async 路径中的阻塞 sleep**：将 `seat_check.py`、`seating.py`、`seat_ui.py`、`notice_manager.py` 中在 `async def` 方法调用链上的 `time.sleep()` 替换为 `await asyncio.sleep()`，使事件循环在等待期间仍可处理其他协程。
- **统一日志输出**：将全项目 55 处 `print()` 调用替换为对应的 `self.logger.*()` 调用，消除日志断层。
- **重构 scroll 方法内部**：提取 `_reversed_if_needed(lst, direction)` helper，消除 `scroll_container_until_element` 中 5 处重复的 `if direction in ("down", "right"): attribute_values_list.reverse()` 逻辑。
- **测试文件归位**：将 4 个根目录下的 `test_*.py` 文件移至 `tests/` 目录，更新 pyproject.toml 中的 testpaths（如有需要）。
- **清理 `_init_handlers` 重复导入**：移除 `app_controller.py` 中 `_init_handlers` 方法体内对已在文件顶部导入的 `NoticeManager` 和 `PartyManager` 的重复 import 语句。

## Capabilities

### New Capabilities

- `async-ui-operations`: 定义 UI 自动化操作（元素等待、动画等待、滑动操作）在 asyncio 上下文中的安全执行规范——同步 UI 操作（Appium driver 调用）保持不变，仅将"纯粹的等待延迟"替换为非阻塞形式。

### Modified Capabilities

- `async-event-loop-safety`: 扩展现有 spec，明确将"命令执行链中的同步 manager 方法内的阻塞 sleep"也纳入需要修复的范围（现有 spec 只涵盖事件处理和兜底退避路径）。

## Impact

- 受影响代码：`src/ushareiplay/managers/seat_manager/seat_check.py`、`src/ushareiplay/managers/seat_manager/seating.py`、`src/ushareiplay/managers/seat_manager/seat_ui.py`、`src/ushareiplay/managers/notice_manager.py`、`src/ushareiplay/core/app_handler.py`（scroll 方法）、全项目所有含 `print()` 的文件、`test_*.py` 根目录文件。
- 运行时行为：seat 检查、notice 设置等命令执行期间，事件循环不再被冻结，timer tick 和消息队列 drain 可以正常推进。
- 无新增第三方依赖。
- 无 API 或配置格式变更。
- 向后兼容：所有改动为纯内部实现替换，对外行为（命令响应、消息格式）不变。
