## 1. 准备：调用点审查

- [ ] 1.1 运行 `grep -rn "expand_seats\|collapse_seats" src/` 确认所有调用点，记录是否在 async 路径上
- [ ] 1.2 运行 `grep -rn "set_default_notice" src/` 确认调用链，验证是否通过 async 路径被调用
- [ ] 1.3 运行 `grep -rn "time.sleep" src/ushareiplay/managers/seat_manager/ src/ushareiplay/managers/notice_manager.py` 列出待替换的完整清单

## 2. SeatUI 方法异步化

- [ ] 2.1 将 `seat_ui.py` 中 `expand_seats()` 改为 `async def expand_seats()`，内部 `time.sleep(0.5)` 改为 `await asyncio.sleep(0.5)`
- [ ] 2.2 将 `seat_ui.py` 中 `collapse_seats()` 改为 `async def collapse_seats()`，内部 `time.sleep(0.5)` 改为 `await asyncio.sleep(0.5)`
- [ ] 2.3 在 `seat_ui.py` 顶部添加 `import asyncio`

## 3. SeatCheck 和 Seating 的 sleep 替换

- [ ] 3.1 在 `seat_check.py` 中 `check_user_specific_seat()` 和 `_handle_occupied_seat()` 内将 `time.sleep()` 改为 `await asyncio.sleep()`；将对 `seat_ui.expand_seats()` 的调用改为 `await self.seat_ui.expand_seats()`
- [ ] 3.2 在 `seating.py` 中找到所有 `time.sleep()` 调用，替换为 `await asyncio.sleep()`；将 `self.seat_ui.expand_seats()` 改为 `await self.seat_ui.expand_seats()`
- [ ] 3.3 在 `seating.py` 和 `seat_check.py` 顶部添加 `import asyncio`（如未导入）

## 4. NoticeManager 的 sleep 替换

- [ ] 4.1 将 `notice_manager.py` 中 `set_default_notice()` 改为 `async def set_default_notice()`
- [ ] 4.2 将其中 `time.sleep(3)` 改为 `await asyncio.sleep(3)`
- [ ] 4.3 在 `notice_manager.py` 顶部添加 `import asyncio`
- [ ] 4.4 找到 `set_default_notice()` 的调用方，更新为 `await notice_manager.set_default_notice()` （预期在 `post_party_create_automation.py`）

## 5. print 统一为 logger

- [ ] 5.1 运行 `grep -rn "print(" src/ushareiplay/ --include="*.py"` 生成完整清单
- [ ] 5.2 替换 `src/ushareiplay/handlers/qq_music_handler.py` 中所有 `print()` 为 `self.logger.*()` 调用
- [ ] 5.3 替换 `src/ushareiplay/core/app_controller.py` 中初始化完成后的 `print()` 为 `self.logger.*()` 或 `print()` 保留（bootstrap 阶段 logger 未就绪的行保留）
- [ ] 5.4 替换 `src/ushareiplay/managers/` 下各 manager 文件中的 `print()` 为 `self.logger.*()` 调用
- [ ] 5.5 替换 `src/ushareiplay/commands/` 下各命令文件中的 `print()` 为 `self.logger.*()` 调用
- [ ] 5.6 替换 `src/ushareiplay/handlers/soul_handler.py` 中的 `print()` 调用
- [ ] 5.7 运行 `grep -rn "print(" src/ushareiplay/ --include="*.py"` 复查，确认只剩 bootstrap 阶段的保留 print

## 6. scroll_container_until_element 重构

- [ ] 6.1 在 `app_handler.py` 的 `AppHandler` 类中添加私有方法 `_reversed_if_needed(self, lst: list, direction: str) -> list`
- [ ] 6.2 将 `scroll_container_until_element` 中 5 处 `if direction in ("down", "right"): attribute_values_list.reverse()` 替换为 `return key, element, self._reversed_if_needed(attribute_values_list, direction)`（或相应的内联调用）

## 7. 测试文件归位

- [ ] 7.1 将 `test_avatar_exit.py` 移动到 `tests/test_avatar_exit.py`
- [ ] 7.2 将 `test_command_parser_no_config_mutation.py` 移动到 `tests/test_command_parser_no_config_mutation.py`
- [ ] 7.3 将 `test_keyword_acl.py` 移动到 `tests/test_keyword_acl.py`
- [ ] 7.4 将 `test_user_canonical_mapping.py` 移动到 `tests/test_user_canonical_mapping.py`
- [ ] 7.5 检查 `pyproject.toml` 中的 `testpaths` 配置，确认 pytest 能发现 `tests/` 目录下的新增测试

## 8. 清理重复导入

- [ ] 8.1 在 `app_controller.py` 的 `_init_handlers()` 方法体内，移除对 `NoticeManager` 和 `PartyManager` 的 `from ... import` 语句（它们已在文件顶部导入）

## 9. 验证

- [ ] 9.1 运行 `python -m py_compile src/ushareiplay/managers/seat_manager/seat_check.py src/ushareiplay/managers/seat_manager/seating.py src/ushareiplay/managers/seat_manager/seat_ui.py src/ushareiplay/managers/notice_manager.py src/ushareiplay/core/app_handler.py` 语法检查
- [ ] 9.2 运行 `python -m py_compile src/ushareiplay/core/app_controller.py` 语法检查
- [ ] 9.3 运行 `uv run pytest -q` 确认全量测试通过
- [ ] 9.4 运行 `grep -rn "time.sleep" src/ushareiplay/managers/seat_manager/ src/ushareiplay/managers/notice_manager.py` 确认替换完整，无遗漏
