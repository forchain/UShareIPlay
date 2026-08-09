## Context

架构评审（评级 Worth exploring，ports & adapters）指出：`OnlineListScraper` 全文直接调用 `handler.element_finder` 和 `handler.gesture_handler`——两跳深入 `SoulHandler` 内部。locality 差：不理解 `SoulHandler` 就无法推理 scraper，也无法在没有完整 `SoulHandler` 的情况下测试它。

评审建议：抽取 UISeen 端口（抽象接口），`OnlineListScraper` 只与端口对话；`SoulHandler` 提供具体适配器。**一个适配器 = 假想 seam，两个适配器 = 真 seam**——测试提供第二个适配器。

## Goals / Non-Goals

**Goals:**
- 定义 `OnlineListUI` 抽象端口（`src/ushareiplay/state/online_list_ui.py`），方法集恰好等于 scraper 使用的 6 个 UI 原语
- 提供生产适配器 `SoulOnlineListUI`（委托 `SoulHandler.element_finder` / `gesture_handler`）
- `OnlineListScraper` 迁移为只通过 `self.ui` 端口访问 UI，删除 `handler` property
- 测试提供第二个适配器 `FakeOnlineListUI`，scraper 可在无 `SoulHandler` 的情况下测试

**Non-Goals:**
- 不改变抓取逻辑（停止条件、DAO 更新、滑动参数）——行为保持型重构
- 不把端口泛化给其他 scraper 使用（目前只有一个消费者；泛化是投机设计）
- 不改变 `element_finder` / `gesture_handler` 本身

## Decisions

### 决策 1: 端口与 scraper 同处 state 包，而非 core/ui

**选择**: `src/ushareiplay/state/online_list_ui.py`。

**理由**:
- 端口属于消费者（hexagonal architecture 惯例），`OnlineListUI` 的方法集由 scraper 的需求定义
- `core/ui/` 存放的是 SoulHandler 侧的实现细节（`element_finder`、`gesture_handler`），端口放在那里会造成双向依赖

### 决策 2: 端口签名机械映射 gesture/element_finder 原语

**选择**: 端口方法签名与底层原语一一对应（`try_find_element(key, log)`、`swipe(x1,y1,x2,y2,duration_ms)` 等），不发明领域化命名。

**理由**:
- 调用点只有 scraper 一处，领域化命名（如 `scroll_online_list()`）会把抓取策略泄漏进适配器
- 机械映射让适配器是纯透传，review 时一眼可验证正确性

### 决策 3: 测试用 FakeOnlineListUI 作为第二适配器，而非 MagicMock

**选择**: 测试文件内定义 `FakeOnlineListUI(OnlineListUI)`，用字典/列表记录调用。

**理由**:
- 继承 ABC 使测试适配器受接口约束——端口签名变化时测试编译期失败，而非运行期静默通过
- 第二个适配器让 seam 从"假想"变"真实"（评审原话）
- 比 MagicMock 链（`scraper._handler.element_finder.try_find_element.side_effect = ...`）更直接表达测试意图

## Risks & Mitigations

**Risk**: `InfoManager._propagate_injected_handler_logger` 仍会向 scraper 注入 `_handler`（本分支上该钩子仍存在）。
**Mitigation**: 注入变成无害的未读属性；`document-info-manager-facade` 变更已删除该钩子，两个变更合并后自然消解。

**Risk**: 端口方法集漏掉某个 UI 调用。
**Mitigation**: 迁移后 grep `self.handler` 在 scraper 中零命中；全量测试 339/339 通过。

## Testing Decisions

**What makes a good test for this change:**
- scraper 测试不再构造 `SoulHandler` 替身，只面对端口
- `test_refresh_online_users_no_op_when_user_count_element_missing` 改为断言端口无交互（`swipes == []`、`clicks == []`），比断言 mock 调用次数更表达行为

**Modules to test:**
- `OnlineListScraper`（现有 `tests/state/test_online_list_scraper.py`，已迁移到 FakeOnlineListUI）
- `UserCountEvent` 调用路径（现有 `tests/test_user_count_event.py`，不受影响）

## Out of Scope

- 把 `PlaybackBroadcaster` 等其他 state 模块也端口化（它们不直接触碰 handler 的 UI 子组件）
- `online_container.location/size` 等元素协议的形式化（Appium ElementWrapper 已是事实标准）
