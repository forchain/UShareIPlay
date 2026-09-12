## 1. 端口定义

- [x] 1.1 统计 scraper 使用的全部 UI 原语：`try_find_element`、`wait_for_element`、`find_child_elements`、`find_child_element`、`swipe`、`click_element_at`
- [x] 1.2 确认 `gesture_handler.swipe` / `click_element_at` 签名，端口机械映射
- [x] 1.3 创建 `src/ushareiplay/state/online_list_ui.py`：`OnlineListUI` ABC + `SoulOnlineListUI` 生产适配器

## 2. Scraper 迁移

- [x] 2.1 `OnlineListScraper` 的 10 处 `self.handler.element_finder.*` / `self.handler.gesture_handler.*` 调用迁移到 `self.ui.*`
- [x] 2.2 删除 `handler` property 与 `_handler` 字段，新增惰性 `ui` property（默认 `SoulOnlineListUI()`）
- [x] 2.3 迁移后 grep 确认 scraper 中 `self.handler` 零命中

## 3. 测试迁移到第二适配器

- [x] 3.1 `tests/state/test_online_list_scraper.py`：定义 `FakeOnlineListUI(OnlineListUI)` 记录调用，替换 MagicMock handler 注入
- [x] 3.2 元素 stub 改为端口字典配置（`ui.elements[...]` / `ui.wait_elements[...]` / `ui.child_element_map`）
- [x] 3.3 no-op 测试改为断言端口无交互

## 4. 验证

- [x] 4.1 全量测试 339/339 通过（含 `tests/state/` 28 个、`tests/test_user_count_event.py`）
