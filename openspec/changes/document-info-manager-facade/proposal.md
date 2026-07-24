## Context

架构评审（评级 Worth exploring）指出：`InfoManager` 是一个未记录的 facade，隐藏了 5 个状态模块（`RoomState`、`PresenceTracker`、`PlaylistState`、`PlaybackBroadcaster`、`OnlineListScraper`），且 `_propagate_injected_handler_logger` 把测试基础设施泄漏进了生产代码。评审给出两条路径：**显式声明为 facade（写 ADR）** 或 **解散 facade 让调用方直连状态模块**。

调用面统计：14 个生产文件、约 50 处调用点，且多数调用点一次穿越 2-3 个状态关注点（如 `radio.py` 同时使用 `player_name`、`current_playlist_name`、`is_user_online`）。解散 facade 会把"哪个状态模块拥有哪个关注点"的知识散播到每个调用方，代价大而行为收益为零。

## Goals / Non-Goals

**Goals:**
- 选择路径 A：将 `InfoManager` 显式声明为 facade，写 ADR-0003
- 从生产代码移除测试基础设施：`__setattr__` 钩子、`_propagate_injected_handler_logger`、`_online_users` / `_playback_info_cache` 兼容属性
- 迁移依赖这些钩子的测试，改为直接向目标状态模块注入测试替身

**Non-Goals:**
- 不迁移任何 `InfoManager` 业务调用方 — facade 接口保持不变
- 不改变 5 个状态模块的实现
- 不删除 facade 的任何委托方法

## Decisions

### 决策 1: 保留 facade 而非解散

**选择**: 路径 A — ADR 显式声明 facade。

**理由**:
- ~50 处调用点、14 个文件的迁移成本 vs 零行为收益
- facade 是单一稳定接缝：一个 import 知道关注点归属；解散后该知识散播到每个调用方
- `tests/state/test_info_manager_facade.py` 已把 facade 作为既定模式覆盖

### 决策 2: 测试直接注入状态模块

**选择**: 删除 `__setattr__` 传播钩子和兼容属性；测试改为 `PlaybackBroadcaster.instance()._soul_handler = mock` 等直接注入。

**理由**:
- 状态模块自身已有 `_logger`/`_handler`/`_soul_handler` 字段 + 惰性 property，天然支持注入
- 生产代码不应携带仅为测试服务的 `__setattr__` 魔法 — 它让"修改 InfoManager 字段"这一动作产生隐式副作用，是理解障碍
- 迁移后测试意图更清晰：替身注入到真正消费它的模块

## Risks & Mitigations

**Risk**: 有其他测试隐式依赖传播钩子（先注入 `_handler` 再触发子模块创建）。
**Mitigation**: 全仓 grep 所有 `info_manager._` 注入点，逐一核对；只有 3 个测试文件使用该模式，全部迁移。全量测试 339/339 通过。

**Risk**: 生产代码使用了兼容属性 `_online_users` / `_playback_info_cache`。
**Mitigation**: grep 确认生产代码仅使用公开方法 `get_online_users()` / `get_playback_info_cache()`。

## Testing Decisions

**What makes a good test for this change:**
- 行为保持：facade 委托测试（`test_info_manager_facade.py`）断言语义不变，仅注入方式改变
- 广播测试（`test_info_manager_broadcast.py`）验证替身注入 broadcaster 后消息分发行为不变

**Modules to test:**
- `InfoManager` facade 委托（现有 `tests/state/test_info_manager_facade.py`）
- `PlaybackBroadcaster` 消息广播（现有 `tests/test_info_manager_broadcast.py`）
- `InfoCommand` release date 缓存（现有 `tests/test_info_command_release_date.py`）

## Out of Scope

- 解散 facade、迁移业务调用方（已明确拒绝，理由记录于 ADR-0003）
- 统一状态模块的 logger 注入方式（如改为构造注入）
- `InfoManager.clear()` 直接操作子模块私有字段的问题（facade 内部的局部问题，不影响调用方）
