## 1. 数据模型与 DAO

- [x] 1.1 新增 `src/models/timer.py`：定义 Timer Tortoise ORM 模型（字段：id IntField pk、key CharField unique、message TextField、target_time CharField、repeat BooleanField、enabled BooleanField、next_trigger DatetimeField null；表名 `timer_events`）
- [x] 1.2 在 `src/models/__init__.py` 中导出 Timer 模型
- [x] 1.3 新增 `src/dal/timer_dao.py`：实现 TimerDAO 静态异步方法（create、get_by_key、list_all、update_next_trigger、update_enabled、delete_by_key、count）
- [x] 1.4 确认 `src/core/db_manager.py` 的 modules 配置已包含 `src.models`（Timer 会被自动发现）

## 2. TimerManager 重构

- [x] 2.1 修改 `_load_timers()`：改为调用 `TimerDAO.list_all()`，将结果转换为 `_timers` 内存字典（以 `key` 字段为 dict key）
- [x] 2.2 删除 `_save_timers()` 方法（全量写文件逻辑废弃）
- [x] 2.3 修改 `add_timer()`：调用 `TimerDAO.create()` 写入 DB，同步更新 `_timers`
- [x] 2.4 修改 `remove_timer()`：调用 `TimerDAO.delete_by_key()` 删除 DB 记录，同步更新 `_timers`
- [x] 2.5 修改 `enable_timer()` / `disable_timer()`：调用 `TimerDAO.update_enabled()` 更新 DB，同步更新 `_timers`
- [x] 2.6 修改 `_trigger_timer()`：repeat 定时器触发后调用 `TimerDAO.update_next_trigger()` 更新 DB；一次性定时器调用 `TimerDAO.update_enabled(False)` 禁用
- [x] 2.7 删除 `load_initial_timers()` 方法及所有 `_initial_timers` / `force_update` 相关代码
- [x] 2.8 删除 `_timers_file` 属性及所有 `timers.json` 文件路径引用

## 3. reload 命令

- [x] 3.1 在 `TimerManager` 中新增 `reload()` 异步方法：调用 `_load_timers()` 重新从 DB 加载，覆盖 `_timers`，返回加载数量
- [x] 3.2 在 `src/commands/timer.py` 的 `process()` 中新增 `reload` 分支，调用 `timer_manager.reload()`，返回 "已从数据库重新加载 N 个定时器"
- [x] 3.3 在 `_show_help()` 中补充 `timer reload` 说明

## 4. 首次迁移逻辑

- [x] 4.1 在 `start()` 方法中，`_load_timers()` 之后判断：若 `_timers` 为空且 `data/timers.json` 存在，则执行迁移
- [x] 4.2 实现 `_migrate_from_json()` 私有方法：读取 `timers.json`，逐条调用 `TimerDAO.create()` 写入 DB，记录迁移日志

## 5. 配置清理

- [x] 5.1 删除 `config.yaml` 中的 `initial_timers` 整段配置
- [x] 5.2 检查 `CommandManager` 或其他调用 `load_initial_timers()` 的地方，移除相关调用代码

## 6. 验证

- [x] 6.1 启动服务，确认首次运行时 `data/timers.json` 中的定时器被正确导入 DB
- [x] 6.2 执行 `timer list` 确认所有定时器显示正常
- [x] 6.3 执行 `timer add` / `timer remove` 确认 DB 实时更新
- [x] 6.4 直接修改 DB 后执行 `timer reload`，确认内存缓存与 DB 同步
- [x] 6.5 重启服务，确认定时器从 DB 加载，`next_trigger` 时间保持正确
