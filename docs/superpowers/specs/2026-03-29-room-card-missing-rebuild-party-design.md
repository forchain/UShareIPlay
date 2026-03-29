## 背景

在 `PartyManager.join_party()` 的“搜索派对并进入”流程中，搜索后会等待 `room_card`（房间卡片）元素出现。线上日志显示在点击搜索按钮后，经常出现 `room_card` 在超时内未出现，从而导致流程直接失败返回，并没有触发后续的“创建/重建派对”流程。

期望行为：**当搜索后找不到房间卡片时，也认为房间已关闭，应自动重建房间（创建派对）**。

## 目标

- 当 `room_card` 在超时内未找到时：
  - 视为派对已关闭
  - 不再尝试进入在线派对（用户选择“直接重建”）
  - 进入既有的创建派对/创建房间流程，确保派对被重建

## 非目标

- 不调整底层 `wait_for_element_plus()` 的等待策略与超时策略
- 不新增新的 UI 选择器或改动 `config.yaml` 元素定义
- 不做与“派对重建”无关的重构

## 设计

### 触发条件

- 位于 `join_party()` 的 `search_entry` 分支内：
  - 已输入派对 ID 并点击搜索按钮
  - `wait_for_element_plus('room_card')` 返回 `None`

### 行为

- 记录 warning 日志：说明未找到房间卡片，按“派对关闭”处理，准备重建
- 尝试点击 `search_back` 返回搜索页/上一层（若存在）
  - 若找不到 `search_back`，则使用系统返回 `press_back()` 兜底（避免卡在搜索结果页）
- 然后继续执行现有创建派对逻辑（`create_party_entry/create_room_entry → ... → create_party_button`）

### 成功标准

- 日志中出现 `Element room_card... not found` 后，不再以 “未找到派对房间→return False” 结束
- 流程会进入创建派对分支并最终点击 `create_party_button`

## 测试计划

- 语法检查：`python -m py_compile src/ushareiplay/managers/party_manager.py`
- 脚本回归：`python test_timer_restart.py`

