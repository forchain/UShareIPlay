# Seat 缓存优先改造自动化测试方案（#345 / #346 / #347 / #348）

> Status: **草案，待 review**
> Owner: agent-e2e-test
> Trigger: manual（用户要求制定方案）
> 关联 Issue: #345（parent spec） / #346 / #347 / #348

本方案覆盖三个垂直切片的自动化验证：

- **#346** SeatObservationManager 暴露 `sync_current_viewport(band)`；`:seat 2 <n>` 直达目标行 + page_source 校验 + 物理点击 + 快照对账。
- **#347** `:seat` 自动寻座内存预选 + 现场核验背离时的同屏空座自愈与跨排重选。
- **#348** `:seat 3 [username]` 查快照直达伴座；`:seat 4 [n]` 查快照与离座状态同步。

父 spec **#345** 的硬指标（cache-first、不再逐桌点击头像弹窗、page-source 验证、closed-loop 状态对账）是贯穿三个 ticket 的共同测试准绳。

---

## 0. 测试分层与执行边界

本项目所有「是否真的就座」的真值最终都要回到 Android/Appium 真机上才能定论，
但本仓库按既有约定（`AGENTS.md`、`agent-e2e-test/SKILL.md`）将验证切成两层：

| 层 | 触发 | 范围 | 时长 | 失败判据 |
|---|---|---|---|---|
| L1 单元 / 集成测试 | `uv run pytest`（PR gate） | 业务逻辑、page-source 解析、状态机、命令路由、reconciliation 闸门 | 秒级 | 任何用例红 → 阻塞合并 |
| L2 真机 E2E | `python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py` 命令路径 | 真实 Soul App、真实 Appium、`events.jsonl` 最小断言链 | 分钟级 | 见第 6 节（事件/DB/UI 三类证据齐备才算 pass） |

**L1 不可替代 L2**：本方案里凡是涉及「点对真机、靠 page_source 取座位号、靠 gesture 点击坐标、靠 UI 锁保证不被 back 抢断」的判定，全部在 L2 真机里跑；L1 只覆盖解析、对账闸门、状态写入、命令委托等可纯 Python 复现的契约。

**L2 不可替代 L1**：策略性判定（自愈重试上限、对账闸门防死循环、focus_count 与快照的同步路径）必须用注入桩单测；E2E 跑这些会变成「靠抖测延长到几分钟」的慢性坑。

`scripts/agent_e2e.py --mode smoke` 不是 E2E，是 runner 自检；任何 ticket 的最终验收不引用它的输出（SKILL.md 硬规则）。

---

## 1. 测试前置与守卫（Guard）

每条 L2 用例开工前必须满足：

1. **CommandReady**（见 `agent/preconditions.md`）
   - `foreground_app == "Soul"`
   - `anchors ⊇ {"message_content", "input_box_entry"}`
   - `pipeline.ui_lock == "unlocked"`
2. **Device Lease**：通过 `e2e_toolbelt start` 拿到本 worktree 的 lease；同一设备若有其它 worktree 在跑，本轮自动 `cleanup-local` 并要求用户确认。
3. **Freshness boundary**：注入命令前记录 `now`；要求 `status.json` 与 `events.jsonl` 的 mtime ≥ now - 30s，且 `run_id` 与 `status.run_id` 一致。
4. **Capability self-check**：`e2e_toolbelt doctor --needs process,input,adb,db,logs,artifacts` 全部绿，否则报告 blocker 不进入下一步。
5. **远端状态**：若 `agent_e2e.remote.host` 在 `config.local.yaml` 里配过，先 `remote-status` + `remote-logs`，需要时 `remote-pause`，绝不在未授权时 `remote-force-stop`（见 `agent-e2e-test/remote-operations.md`）。

> 守卫失败的 E2E 不算「测试失败」，算 blocker 报告。

---

## 2. 共享测试夹具与契约

新用例复用以下既有资产，避免再开一套语义不一致的替身：

- `tests/seat_fixtures.py` —— `FakeElementFinder`、`RawSeatDesk`、`FakeController`（`ui_session` 异步上下文管理器）、`FakeSeatUI`、`make_handler`、`soul_elements()`。
- `tests/fixtures/seat_dom/*.xml` —— 真机 `page_source` dump 裁剪：
  - `collapsed_top_no_anchor.xml`（折叠视口 + 无数字锚点）
  - `expanded_top_with_anchor.xml`（顶相位展开）
  - `expanded_scrolled_bottom.xml`（底相位展开）
  - `collapsed_scrolled_after_collapse.xml`（折叠中段视口）
- `tests/test_seat_observation.py` 已确立的「真机视图夹具 + 替身同形」模式是 #341 后所有座位测试的事实标准，新 L1 用例沿用。
- `events.jsonl` 最小断言链（见 `agent/event_taxonomy.md`）：
  `queue.enqueue → queue.drain.start → command.received → command.dispatch → command.result → queue.drain.end`。
- 日志铁律（`AGENTS.md`）：常规轮询空转不打 INFO/CRITICAL，只在 DEBUG；任何监控类测试必须验证这一点。

---

## 3. Ticket #346 测试方案：viewport sync + `:seat 2 <n>` 直达

### 3.1 触发 / 场景

- **trigger**: `manual`（用户要求验证 `:seat 2` 直达 + 防 back-trigger）
- **scenario**: `dev`（实现期反复验证）/ `test`（最终验收）
- **lifecycle**: `dev` 用 `e2e_toolbelt start --scenario dev`；`test` 先校验 freshness 与 readiness，再决定 reuse / restart。

### 3.2 L1 单元 / 集成（必跑）

文件：`tests/test_seat_viewport_sync.py`（新建）、`tests/test_seat_take_targeted.py`（新建）。

#### 3.2.1 `sync_current_viewport(band)` 契约

| # | 用例 | 期望 | 证据来源 |
|---|---|---|---|
| V1 | 顶相位 `band="top"`：传入 `expanded_top_with_anchor.xml`，调用后 `seats[1..8]` 已更新 | `seats[1].occupied=True, is_owner=True`；`seats[5].occupied=True`；其余 `is_empty=True` | `_read_visible_seats(..., band="top")` 单测 + 现状 `test_real_top_phase_maps_leading_desks_without_anchor` |
| V2 | 底相位 `band="bottom"`：传入 `expanded_scrolled_bottom.xml` | `seats[5..12]` 已更新 | 复用现有 `test_real_bottom_phase_maps_trailing_desks_without_anchor` |
| V3 | 中段视口不带相位 → 身份未知，整屏丢弃 | `sync_current_viewport()`（默认 `band=None`）不写入任何座位 | 复用 `test_mid_scroll_viewport_stays_unknown` |
| V4 | `band` 与几何不符时返回 `False` 且不写快照 | `seats` 不变 | 复用 `test_phase_mapping_refuses_when_panel_is_at_the_other_end` |
| V5 | DOM 解析失败（page_source 抛错）→ 返回 `False` 且快照原值保留 | `seats[1].username == "Outlier"`（预设）保持不变 | 新增：mock `driver.page_source` 抛 `WebDriverException` |
| V6 | 同步完成后写入 `band_change_reason = None` 清零（避免与被动观测闸门互相污染） | `_band_change_reason is None` | 新增（与现有 `observe_visible_desks` 行为对齐） |

#### 3.2.2 `:seat 2 <n>` 直达

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| T1 | 快照里 5 号位空 → 直接滚动到 row 1（desk 2/3）→ `sync_current_viewport(band="top")` 验证空 → 物理点击 → 写入快照 | `seats[5].occupied=True, is_owner=True`；`gesture_handler.click_at(center_x, center_y)` 被调用一次；`_last_focus_count += 1`；`_reconciled_focus_count == _last_focus_count`；`collapse_seats()` 被调用 | 新增 |
| T2 | 滚动到目标行后 page_source 显示 5 号位被占 → 立即返回错误，**不**点击 | `gesture_handler.click_at.assert_not_called()`；`seats[5]` 在快照里更新为占座但**不**是 owner；返回 `{'error': 'Seat 5 is already occupied by <昵称>'}` | 新增（验收 #5 对账保护） |
| T3 | 物理点击坐标取自 `page_source` 的 `bounds`（不是 `ElementWrapper.get_web_element()`） | mock 的 `click_at` 入参 = `(bounds.x + w/2, bounds.y + h/2)`；不再依赖 `left_seat.click()` | 新增（验收 #3） |
| T4 | 越界座位（13/0/-1）被 `coerce_int` 兜住，**不**触发任何 UI 动作 | `find_elements` 未被调用；返回 error dict | 复用既有 `test_seat_2_delegates_specific_seat_to_seat_management` 风格 |
| T5 | 滚动手势只滚到目标行（row 0/2），不再触发 row 1 中间行的二次滚动 | mock `gesture_handler.swipe` 仅被调用一次 | 新增（验收 #2：「不再逐桌扫描」） |
| T6 | 验证失败时不写入 owner 标记、不预增 `_last_focus_count` | 失败路径下 `_last_focus_count` 维持原值 | 新增 |

#### 3.2.3 关闭对账闸门（验收 #6）

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| A1 | `:seat 2 5` 成功后，下一轮 `focus_count` 事件报 +1 → 不触发 `expand_rescan_and_collapse` | mock `expand_rescan_and_collapse` 未被 await | 新增（核心回归点） |
| A2 | `:seat 2 5` 失败后，下一轮 `focus_count` 事件报 +1 → 仍按既有闸门逻辑处理（闸门未被打上 reconciled 标记） | `_reconciled_focus_count is None`，人数背离仍可触发重扫 | 新增 |
| A3 | 已有 `test_same_focus_count_is_reconciled_only_once` 继续绿灯（防退化） | 通过 | 既有用例 |

### 3.3 L2 真机 E2E

#### 3.3.1 `e2e_take_seat_2_success`：`:seat 2 5` 真机成功路径

- 生命周期：`dev`（实现期）；最终验收 `test`。
- 前置：CommandReady + 当前房间 5 号位确认空座（`!dump` 后人工或脚本确认）。
- 注入：

  ```bash
  python .agents/skills/agent-e2e-test/scripts/e2e_toolbelt.py inject --text ':seat 2 5'
  ```

- 证据：
  - `events.jsonl` 出现命令最小链 + `command.result.ok == True`。
  - `status.json.pipeline.ui_lock` 在滚动期间为 `locked`，结束后 `unlocked`（证明 `sync_current_viewport` 走的是真实 `ui_session`，不是裸锁）。
  - DB：`seat_reservations` 表里 owner 用户对应行被 `update_reservation_start_time` 刷新过（如适用）。
  - `page_source.xml` 显示 5 号位是「群主」或 `label=群主`。
  - 日志：`[FocusSeatObservation] 专注麦位状态变更` 触发源应为「可视区域变更」而非「专注人数背离展开重扫」（证明没走背离闸门）。

#### 3.3.2 `e2e_take_seat_2_occupied`：`:seat 2 5` 撞坐

- 前置：让测试用户在 5 号位先坐稳（脚本辅助命令 `:seat 2 5` 由另一身份注入，或 `adb shell input` 模拟）。
- 期望：`command.result` 带 error，`events.jsonl` 中无 `gesture_handler.click_at` 痕迹（已用 mock 替身），真机里**不**会出现「点到了 5 号位头像」导致的资料弹窗（用 `adb-screenshot` 二次验证：截图里没有弹窗）。
- 期望的副作用：`SeatObservationManager.seats[5]` 被对账刷新（可在 `status.json` 或下一个 dump 里看到），`_last_focus_count` 与 `_reconciled_focus_count` 不变。

#### 3.3.3 `e2e_anti_trigger_rescan`：`:seat 2 5` 成功后 focus_count 增量不触发重扫

- 执行顺序：
  1. `:seat 2 5` 成功（用例 3.3.1）。
  2. 让脚本模拟一次「room event: focus_count=N+1」——L2 实现里这通常以另一种事件（`focus_count` text 变更）自然发生；如不可控，用 `inject --text ':focus'` 或 dev-only probe 命令。
  3. 在 `events.jsonl` 里断言 `expand_rescan_and_collapse` 相关日志（关键词 `专注人数背离展开重扫`）**不**出现。
- 阻断条件：若发现「`:seat 2 5` 后 _last_focus_count 仍为旧值 / _reconciled_focus_count 未登记」，则算 `#346` 验收失败。

### 3.4 退出判据

- L1 用例全绿。
- L2 `e2e_take_seat_2_success` 与 `e2e_take_seat_2_occupied` 均产出事件链 + DB + UI 三类证据；`e2e_anti_trigger_rescan` 通过。
- 既有 `tests/test_seat_observation.py` 与 `tests/test_focus_count_seat_event.py` 全绿（防回归）。

---

## 4. Ticket #347 测试方案：`:seat` 内存预选 + 自愈重选

### 4.1 触发 / 场景

- **trigger**: `manual`
- **scenario**: `dev` / `test`
- **lifecycle**: 同 #346
- **依赖**：#346 必须先 green，本节才进入 L2。

### 4.2 L1 单元 / 集成

文件：`tests/test_seat_find_owner_optimistic.py`（新建）。

#### 4.2.1 内存预选路径（验收 #1）

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| F1 | 快照 `{1: 群主(占), 2: 空闲, 5: 张三(占), 6: 空闲}` → `:seat` 命中 6 号位作为伴座候选 | `find_owner_seat` **不**调用 `expand_and_find_desks`；直接走 `_plan_candidate_from_snapshot` 路径 | mock `expand_and_find_desks` 未被调用 |
| F2 | 快照全空 → 选中 1 号位作为首个空座候选 | `gesture_handler.swipe` 仅滚动到 row 0 一次 | 验收 #1：跳过中段扫描 |
| F3 | 快照里有人但无伴座候选 → 选中第一个空座位号最低的 | 行 0/1/2 都可能，断言滚动只发生一次（到目标 row） | 验收 #1 |

#### 4.2.2 现场核验 + 自愈（验收 #2/#3/#4）

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| F4 | 预选 6 号位 → 滚动 → `sync_current_viewport(band="top")` 报 6 号位被占 → 优先看同视口空座（8 号位空）→ 物理点击 8 号位 | **不**再次 `swipe`；`click_at` 调用一次（8 号位）；最终 `seats[8].occupied=True, is_owner=True` | 验收 #3「同屏内不重复滚动」 |
| F5 | 预选 6 号位 → 视口全占 → 重读快照 → 滚动到下一候选 row → 重试 | 累计 `swipe` 调用次数 = 已试候选数；最多 3 次 | 验收 #4「跨排重选」+ 验收 #5「≤ 3 次」 |
| F6 | 3 次重试均失败 → 返回 `{'error': 'No available seat found after 3 attempts'}` | `_last_focus_count` 不变 | 验收 #5 |
| F7 | 滚动到 row 2 时 `sync_current_viewport(band="bottom")` | mock `sync_current_viewport` 入参 = `"bottom"` | 验收 #2 phase 传播 |

#### 4.2.3 状态对账闸门（验收 #6/#7）

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| F8 | `:seat` 成功后 `_last_focus_count += 1`、`_reconciled_focus_count == _last_focus_count` | 内部状态对齐 | 验收 #6 |
| F9 | 成功后下一轮 focus_count +1 事件 → 不触发 `expand_rescan_and_collapse` | mock 未 await | 验收 #6 防 back-trigger |
| F10 | 成功后调用 `collapse_seats()` | mock 被 await 一次 | 验收 #7 |

#### 4.2.4 反退化（与 #346 同源）

| # | 用例 | 期望 |
|---|---|---|
| F11 | 既有 `test_same_focus_count_is_reconciled_only_once` 全程绿灯 | 通过 |
| F12 | `test_collapsed_seats_do_not_overwrite_third_row_snapshot` 仍成立 | 通过（不在 `:seat` 路径里推平折叠不可见的座位） |

### 4.3 L2 真机 E2E

#### 4.3.1 `e2e_seat_owner_companion`：`:seat` 自动伴座

- 前置：群主已在 1 号位，5 号位有「张三」普通用户。
- 注入：`:seat`
- 证据：
  - 群主最终坐在 5 号位的同桌空座（即 6 号位）。
  - `events.jsonl` 中**只**有一次 `swipe`（滚到 row 1）；无「逐桌扫描 `for desk_index in range(6)`」产生的重复 scroll / click_at 痕迹。
  - `[FocusSeatObservation] 专注麦位状态变更` 触发源为「可视区域变更」。
  - DB：`seat_reservations` 中对应用户被刷新。

#### 4.3.2 `e2e_seat_owner_self_heal`：自愈重选

- 前置：脚本先把 5 号位的同桌空座抢坐（另一身份执行 `:seat 2 6`），再让 owner 触发 `:seat`。
- 期望：owner 在不重新展开面板的前提下立刻落到下一个同屏空座；否则滚到下一候选；最多 3 次。
- 证据：`artifacts/<run_id>/page_source.xml` 显示最终 owner 在正确位子；`events.jsonl` 中可观察到「`sync_current_viewport` 报占座 → fallback」链路。

#### 4.3.3 `e2e_seat_owner_no_trigger_rescan`：防 back-trigger

- 执行顺序：用例 4.3.1 成功后注入一条引发 `focus_count` 变化的命令（dev probe 或房间自然事件）。
- 期望：`expand_rescan_and_collapse` 不被调用；日志无「专注人数背离展开重扫」。
- 证据：log regex 断言失败即为测试失败。

### 4.4 退出判据

- L1 全绿。
- L2 `e2e_seat_owner_companion` 与 `e2e_seat_owner_self_heal` 端到端通过；`e2e_seat_owner_no_trigger_rescan` 不产生「背离展开」日志。
- 不动既有 L1 用例：`test_seat_observation.py`、`test_focus_count_seat_event.py`、`test_seat_off_command.py`。

---

## 5. Ticket #348 测试方案：`:seat 3` / `:seat 4` 快照驱动

### 5.1 触发 / 场景

- **trigger**: `manual`
- **scenario**: `dev` / `test`
- **依赖**：#346 / #347 全 green 才能进入本节 L2。

### 5.2 L1 单元 / 集成

文件：`tests/test_seat_accompany_snapshot.py`（新建）、`tests/test_seat_off_sync.py`（新建）。

#### 5.2.1 `:seat 3 [username]` 伴座

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| C1 | 快照里张三在 5 号位、6 号位空 → `:seat 3 张三` | **不**逐桌点头像弹窗；mock `state_element.click` / `press_back` **不**被调用；`sync_current_viewport(band="top")` 被调用一次；最终 `seats[6].occupied=True, is_owner=True` | 验收 #1 |
| C2 | 快照里张三在 5 号位、6 号位**也**被人占 → 立即返回 error，不做任何 UI 动作 | mock `swipe` / `sync_current_viewport` 均未被调用；返回 `{'error': 'User 张三 has no empty adjacent seat'}` | 验收 #2 |
| C3 | 快照里找不到张三、且无未识别占座（`username is None`）→ 立即 error | 同 C2，不触发展开 | 验收 #2 |
| C4 | 快照里找不到张三、但有 `username is None` 的占座（未识别）→ 触发 `expand_rescan_and_collapse` 重扫 → 重扫后仍找不到 → 返回 error | mock `expand_rescan_and_collapse` 被调用一次 | 验收 #3（#348 acceptance #3） |
| C5 | 滚动到目标 row 时 `sync_current_viewport` 报伴邻槽位**实际**被占（背离）→ 不点击、刷新快照、返回 error | `gesture_handler.click_at.assert_not_called()` | 验收 #5/#6 |
| C6 | 成功路径：伴座后 `_last_focus_count += 1`、`_reconciled_focus_count == _last_focus_count` | 内部状态对齐 | 验收 #7 |
| C7 | 失败路径也调用 `collapse_seats()` 收尾 | mock 被调用 | 验收 #8 |
| C8 | partner 是 owner 自身的快照分支（理论上 `:seat 3 owner`）→ 仍走伴座逻辑（不会出现 `_take_seat` 拒绝 owner） | 覆盖一行 | 边界用例 |

#### 5.2.2 `:seat 4` 离座

| # | 用例 | 期望 | 备注 |
|---|---|---|---|
| O1 | `:seat 4`（不带参数）→ 快照里有 owner → 直接 scroll 到 owner 的 desk → `sync_current_viewport` → 点击 → 弹窗确认 → 离座 | `_last_focus_count -= 1`；`_reconciled_focus_count == _last_focus_count`；`seats[owner_seat].occupied=False`；`collapse_seats()` 被调用 | 验收 #7/#8 |
| O2 | `:seat 4` 快照里 owner 不在任何座位 → 立即 error | mock `swipe` / `sync_current_viewport` 未被调用；返回 `{'error': 'Owner is not on any seat'}` | 沿用既有 `test_seat_off_owner_returns_error_when_owner_not_found` 但加上「无 UI」断言 |
| O3 | `:seat 4 5` 快照里 5 号位空 → 立即 error | mock `swipe` 未被调用 | 复用既有 `test_seat_off_specific_seat_clicks_target_seat_and_seat_off_button` 的反面 |
| O4 | `:seat 4 5` 滚动后 `sync_current_viewport` 报 5 号位**实际**已不是目标占座（与快照背离）→ 不点击，刷新快照，返回 error | `click_at.assert_not_called()` | 防误踢 |
| O5 | 离座成功后下一轮 focus_count -1 事件 → 不触发 `expand_rescan_and_collapse` | mock 未 await | 验收 #7 防 back-trigger |
| O6 | 失败路径也调用 `collapse_seats()` 收尾 | mock 被调用 | 验收 #8 |

### 5.3 L2 真机 E2E

#### 5.3.1 `e2e_seat_3_success`：`:seat 3 张三` 直达伴座

- 前置：5 号位张三在场，6 号位空。
- 注入：`:seat 3 张三`
- 证据：
  - 群主落在 6 号位。
  - `events.jsonl` 中无 `wait_for_any_element(['souler_name', 'user_name'])` 痕迹（旧实现逐桌点头像）；只看到一次 `sync_current_viewport` + 一次 `click_at`。
  - DB / `page_source` 双向验证。
  - `adb-screenshot`：过程中无资料弹窗截图（排除「被 back 抢断」的污染）。

#### 5.3.2 `e2e_seat_3_partner_occupied`：伴邻撞坐

- 前置：让 6 号位也被占。
- 期望：`command.result` error，`page_source.xml` 显示 owner 没有出现在任何空位；`collapse_seats()` 被调用（从日志中 grep `Collapsed seats`）。

#### 5.3.3 `e2e_seat_3_unknown_with_unverified`：触发重扫兜底

- 前置：脚本清掉张三在 5 号位的快照昵称（让占座出现但 `username=None`）。
- 期望：`expand_rescan_and_collapse` 被调用一次；若重扫后仍未识别到张三 → error。
- 证据：日志里 `专注人数背离展开重扫` 或 `Seat change with unknown destination ... triggering full rescan`。

#### 5.3.4 `e2e_seat_4_owner`：owner 离座

- 前置：群主已就座（5 号位）。
- 注入：`:seat 4`
- 证据：5 号位回到空；`page_source.xml` 显示 `leftTvDefaultName="点击入座"` 或 `label="5"`；`seat_reservations` 表中对应行被删除或过期。

#### 5.3.5 `e2e_seat_4_specific`：`:seat 4 5` 指定离座

- 同 5.3.4，但用带参数形式。
- 额外断言：`_last_focus_count -= 1`（通过下一个 `focus_count` 事件不触发重扫来佐证）。

#### 5.3.6 `e2e_seat_off_no_trigger_rescan`：离座防 back-trigger

- 5.3.4 成功后注入一条 `-1` 的 focus_count 事件（dev probe），断言无「背离展开」日志。

### 5.4 退出判据

- L1 全绿。
- L2 `e2e_seat_3_success` / `e2e_seat_3_partner_occupied` / `e2e_seat_3_unknown_with_unverified` / `e2e_seat_4_owner` / `e2e_seat_4_specific` / `e2e_seat_off_no_trigger_rescan` 全通过。
- 既有 `test_seat_off_command.py`、`test_seat_management_interface.py` 保持绿灯。

---

## 6. L2 通用证据规范（覆盖三个 ticket）

每个 ticket 的 E2E 用例都按以下三类证据齐备才算 pass：

1. **事件证据**（`events.jsonl`）
   - 命令最小链完整（见 `agent/event_taxonomy.md`）。
   - 命令结果 `ctx.prefix == "seat"`、`ctx.success == True/False`。
   - 失败时 `ctx.error` 含语义信息（如 `"Seat 5 is already occupied by 张三"`）。

2. **DB 证据**（`data/soul_bot.db`）
   - `:seat 1` / `:seat 3` / 离座后，`seat_reservations` 表行变化（仅在有 reservation 流程的命令下断言；`:seat 2` 与 `:seat 4` 不强制）。
   - 工具：`e2e_toolbelt db-query --sql "SELECT user_id, seat_number FROM seat_reservations WHERE ..."`。

3. **UI / 日志证据**
   - `page_source.xml` 显示目标位子的最终状态。
   - `screenshot.png` 存在且非空（用 `e2e_toolbelt adb-screenshot` 或 runner 自动 dump）。
   - 日志 grep：
     - 期望出现（按 ticket）：
       - `[FocusSeatObservation] 专注麦位状态变更 (触发源: 可视区域变更, ...)`（不应是「专注人数背离展开重扫」）。
       - `Expanded seats` / `Collapsed seats`（操作面板生命周期）。
     - 期望**不**出现：
       - 「Focused divergence detected ... Triggering active expansion rescan」（防 back-trigger 失败的红线）。
       - 「Failed to expand seats for full rescan」（除非该用例就是测背离重扫）。

报告一律走 `scripts/agent_e2e.py` 或手写 `artifacts/<run_id>/agent_e2e_report.md`，字段：`trigger / scenario / lifecycle_action / injection_channel / readiness anchors / assertion summary / db checks / log checks / ui checks / blocker`。

---

## 7. 失败 / Blocker 处理

按 `agent-e2e-test/SKILL.md` 第 7 节：

1. **指向可修复问题**（如 `sync_current_viewport` 没把 `band` 传透）：
   - 改实现 → 先 `uv run pytest -q tests/test_seat_viewport_sync.py` 重跑 L1 → 再用 `e2e_toolbelt start --scenario dev` 跑对应 E2E。
2. **环境阻塞**（Appium/账号/device lease）：
   - 报告 blocker + 已收集证据（`page_source.xml`、`events.jsonl`、`adb-screenshot`）。
   - 用 `record-gap --kind blocker` 写入 `agent/known_issues.md`。
3. **架构层缺口**（如工具无法注入纯「focus_count +1」事件）：
   - 写入 `agent/questions.md`，等用户决策；不要脚本绕过 Agent 的 pass/fail 判断。

---

## 8. 风险与待用户确认项

下列项需要用户在 review 时确认；不解决前不进 L2：

| # | 问题 | 影响的用例 | 默认假设 |
|---|---|---|---|
| R1 | 真机房间状态不稳（占座会随用户进出变化）：是否允许脚本在 L2 里用 `:seat 2 5` 抢另一个测试身份的就座？ | #346 E2E「撞坐」分支 | 默认允许；后续 dev probe 命令需要实现 `devprobe` 类型接入 |
| R2 | 「dev probe」命令（注入 `focus_count ±1`）是否已在 bot 里？若没有，方案 R3 是否需要先在 `commands/` 里加 stub 命令？ | `e2e_anti_trigger_rescan` / `e2e_seat_off_no_trigger_rescan` | 默认走 dev-only 钩子，不污染生产 |
| R3 | DB schema 里 `seat_reservations` 是否是 `:seat 2 / :seat 4` 关心的表？读 PR #345「out of scope」判断不需要改 schema，但 L2 DB 断言是否够用？ | 所有 ticket 的 DB 证据 | 默认按既有表，不引入新表 |
| R4 | L1 是否要在 `tests/conftest.py` 加自动 reset `SeatObservationManager` 的 fixture？ | 所有新 L1 用例 | 默认沿用 `tests/test_seat_observation.py` 里 `reset_observation` autouse 风格 |
| R5 | 真机 lease 持有方：本 worktree 默认独占；如有其它 worktree 在排队，是否用 `cleanup-local` 强清？ | 启动阶段 | 默认不清其它 worktree，只警告并要求用户确认（`SKILL.md` 硬规则） |

---

## 9. 测试文件落点总览

| Ticket | 新 L1 文件 | 新 L2 / 复用的现有能力 |
|---|---|---|
| #346 | `tests/test_seat_viewport_sync.py`、`tests/test_seat_take_targeted.py` | `e2e_take_seat_2_success`、`e2e_take_seat_2_occupied`、`e2e_anti_trigger_rescan` |
| #347 | `tests/test_seat_find_owner_optimistic.py` | `e2e_seat_owner_companion`、`e2e_seat_owner_self_heal`、`e2e_seat_owner_no_trigger_rescan` |
| #348 | `tests/test_seat_accompany_snapshot.py`、`tests/test_seat_off_sync.py` | `e2e_seat_3_success`、`e2e_seat_3_partner_occupied`、`e2e_seat_3_unknown_with_unverified`、`e2e_seat_4_owner`、`e2e_seat_4_specific`、`e2e_seat_off_no_trigger_rescan` |

既有依赖复用（不在本方案改动范围）：
`tests/test_seat_observation.py`、`tests/test_seat_off_command.py`、`tests/test_seat_management_interface.py`、`tests/test_focus_count_seat_event.py`、`tests/seat_fixtures.py`、`tests/fixtures/seat_dom/*.xml`。

---

## 10. 端到端执行顺序

1. **L1 先行**：三个 ticket 各自新增的 L1 用例随 PR 进入 `uv run pytest`，任何一个红 → 阻塞 PR。
2. **L2 验收按依赖**：
   - #346 全部用例通过 → 标记 #346 done。
   - 复用 #346 实现的 `sync_current_viewport` / 对账闸门，跑 #347 L2 → 标记 #347 done。
   - 复用以上两者，跑 #348 L2 → 标记 #348 done。
3. **回归**：`tests/test_seat_observation.py` + `tests/test_focus_count_seat_event.py` + `tests/test_seat_management_interface.py` 在最终 PR 合并前再跑一次全量，确保被动观测与事件链未被破坏（#345 第 18 条用户故事）。
4. **报告归档**：每个 E2E 写一份 `agent_e2e_report.md` 进 `artifacts/<run_id>/`；最终 ticket 关闭时把链接附到对应 Issue 评论里（不私自 archive，遵循 `openspec-archive-change` skill 的「用户决策」原则）。