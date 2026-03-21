## Why

定时器配置存储在 `config.yaml` 中，每次修改都需要重启服务才能生效，而定时器需要频繁更新。将定时器配置迁移到数据库后，更新立即生效，无需重启。

## What Changes

- **新增** `src/models/timer.py`：Timer Tortoise ORM 模型
- **新增** `src/dal/timer_dao.py`：TimerDAO，提供完整 CRUD 操作
- **修改** `src/core/db_manager.py`：注册 Timer 模型
- **修改** `src/managers/timer_manager.py`：读写操作改为 DAO 调用，删除 timers.json 逻辑，删除 `force_update` / `_initial_timers` 相关代码；首次启动时若 DB 为空则从现有 `timers.json` 自动导入
- **修改** `config.yaml`：**BREAKING** 删除 `initial_timers` 整段配置

## Capabilities

### New Capabilities

- `timer-db-storage`：定时器配置持久化到 SQLite 数据库，通过 Tortoise ORM 读写，支持实时生效

### Modified Capabilities

- （无需求层面变更，timer 命令的对外行为不变）

## Impact

- `src/managers/timer_manager.py`：核心改动，内存与持久化的衔接方式改变
- `src/models/`、`src/dal/`：新增文件
- `config.yaml`：删除 `initial_timers` 段（破坏性变更，但迁移自动处理）
- `data/timers.json`：废弃，不再读写
- 数据库 schema：新增 `timers` 表，首次启动时自动创建
