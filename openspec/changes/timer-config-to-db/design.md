## Context

当前 `TimerManager` 使用两级存储：
- `config.yaml` 的 `initial_timers` 段作为"种子"数据，每次启动时通过 `load_initial_timers()` 写入
- `data/timers.json` 作为运行时持久化文件，通过 `_load_timers()` / `_save_timers()` 读写

`force_update` 标志控制启动时是否用 config 数据覆盖已有 JSON 数据。这套机制使"定时器配置"和"运行时状态"混杂在同一个 JSON 文件中，且每次修改都依赖重启。

目标：用 SQLite（通过 Tortoise ORM）替代 `timers.json`，成为定时器的唯一持久化层，与项目其他 DAO（`KeywordDAO`、`UserDAO` 等）保持一致风格。

## Goals / Non-Goals

**Goals:**
- Timer 数据完全由 DB 管理，`_save_timers` / `_load_timers` 改为 DAO 调用
- 删除 `timers.json` 读写逻辑、`force_update`、`_initial_timers` 相关代码
- 删除 `config.yaml` 里的 `initial_timers` 整段
- 平滑迁移：首次运行若 DB 为空则自动从现有 `timers.json` 导入

**Non-Goals:**
- 不改变 `timer` 命令的对外接口和用户体验
- 不引入新的定时器功能（如 cron 表达式、多频率重复等）
- 不添加定时器 Web 管理界面

## Decisions

### 决策 1：Timer 模型字段设计

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `IntField(pk=True)` | 自增主键，与项目其他模型一致 |
| `key` | `CharField(unique=True)` | 业务唯一标识（如 "notice_0"） |
| `message` | `TextField` | 触发时推送的命令/消息 |
| `target_time` | `CharField(8)` | HH:MM 格式，用于重置 next_trigger |
| `repeat` | `BooleanField` | 是否每日重复 |
| `enabled` | `BooleanField` | 是否激活 |
| `next_trigger` | `DatetimeField(null=True)` | 下次触发时间 |

表名为 `timer_events`，与现有 `enter_events`、`exit_events`、`return_events` 命名规范一致。

**为什么用整数主键 + key 字段**：与项目所有现有模型（`EnterEvent`、`Keyword`、`User` 等）保持一致，均使用自增整数 id；业务标识（如 "notice_0"）作为 `key` 字段单独存储，加 unique 约束。

### 决策 2：TimerManager 内存缓存保留

`_timers` 内存字典保留，key 为业务标识字符串（原 `timer_id`，现对应模型的 `key` 字段），作为运行时检查用的缓存（每秒轮询不适合直接查 DB）。写操作（add/remove/enable/disable/update next_trigger）同步更新内存 + 异步写 DB。

**替代方案考虑**：每次轮询直接读 DB → 每秒一次 DB 查询对 SQLite 可接受，但改动更大，且不必要。保留内存缓存是最小改动路径。

### 决策 3：平滑迁移策略

启动时的迁移逻辑：
```
IF DB timers 表为空:
    IF data/timers.json 存在:
        从 timers.json 导入所有数据到 DB
    ELSE:
        DB 为空，无需处理（用户通过 timer add 手动添加）
ELSE:
    直接从 DB 加载到内存，跳过 timers.json
```

迁移完成后 `timers.json` 不再读写（保留文件作备份，不删除）。

**不保留 config.yaml 种子机制**：迁移后数据库是单一真相，config 种子会造成"重启覆盖用户修改"的问题，应完全消除。

### 决策 4：`_save_timers` 的替换粒度

不保留 `_save_timers` 作为统一写入口，改为在每个操作（add/remove/enable/disable/update_next_trigger）中直接调用对应 DAO 方法。这样与项目其他 manager 的风格一致，也避免全量覆盖写。

### 决策 5：新增 `timer reload` 命令

直接修改数据库（通过 SQL 工具绕过接口）时，内存缓存 `_timers` 不会自动感知变更。`timer reload` 命令强制从 DB 重新加载，覆盖内存缓存，使直接改 DB 的修改立即生效。

实现路径：`timer reload` → `TimerManager.reload()` → `await _load_timers()` → 返回加载数量。

**不做自动轮询同步**：每秒检测 DB 变化会增加不必要的复杂度，手动 reload 对运维场景足够。

## Risks / Trade-offs

- **[风险] 首次迁移后 timers.json 和 DB 不同步** → 迁移只做一次（DB 为空时），之后 timers.json 被忽略，无混淆风险
- **[风险] Tortoise 异步上下文** → TimerManager 已全面使用 async/await，DAO 调用兼容
- **[风险] DB 写失败但内存已更新** → 与现有 JSON 写失败的风险等级相同，暂不做额外回滚处理

## Migration Plan

1. 部署新版本（含 Timer 模型和迁移逻辑）
2. 首次启动：自动检测 DB 为空 → 从 `timers.json` 导入
3. 验证：通过 `timer list` 确认所有定时器正常加载
4. 后续启动：直接从 DB 加载，`timers.json` 不再使用

**回滚**：回滚到旧版本时，旧版 `timers.json` 仍存在（未删除），可直接恢复。
