## 1. 路径决策与调用面统计

- [x] 1.1 统计 `InfoManager` 调用面：14 个生产文件、约 50 处调用点，多数调用点穿越多个状态关注点
- [x] 1.2 确认状态模块自身支持 `_logger`/`_handler`/`_soul_handler` 字段注入（惰性 property 模式）
- [x] 1.3 确认生产代码未使用 `_online_users` / `_playback_info_cache` 兼容属性

## 2. 移除生产代码中的测试基础设施

- [x] 2.1 删除 `InfoManager.__setattr__` 钩子与 `_propagate_injected_handler_logger`
- [x] 2.2 删除 5 个惰性子模块 property 中的传播调用
- [x] 2.3 删除 `_online_users` / `_playback_info_cache` 兼容属性（含 setter）
- [x] 2.4 更新类 docstring：显式声明 facade 并指向 ADR-0003

## 3. 迁移依赖注入钩子的测试

- [x] 3.1 `tests/state/test_info_manager_facade.py`：fixture 改为向各状态模块直接注入 fake logger；`_playback_info_cache` 注入迁移到 `PlaybackBroadcaster`
- [x] 3.2 `tests/test_info_manager_broadcast.py`：新增 `_inject_broadcaster` 辅助函数，`_handler`/`_logger`/`_playback_info_cache` 全部改为注入 `PlaybackBroadcaster.instance()`
- [x] 3.3 `tests/test_info_command_release_date.py`：`_online_users` 注入迁移到 `PresenceTracker`，`_playback_info_cache` 迁移到 `PlaybackBroadcaster`

## 4. ADR 与验证

- [x] 4.1 写 `docs/adr/0003-info-manager-facade.md`：记录 facade 决策、拒绝解散路径的理由、测试注入新约定
- [x] 4.2 全量测试 339/339 通过
