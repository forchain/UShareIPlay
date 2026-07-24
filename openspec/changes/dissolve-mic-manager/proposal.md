## Context

`MicManager`（56 行）是一个纯委托浅层模块：它的 `toggle_mic()` 仅把 `ui_actions.toggle_mic()` 返回的 `{'error': 'Failed to switch to app'}` 翻译为 `{'error': 'Failed to switch to Soul app'}`，其余全部透传。它的 `get_mic_status()` 没有任何调用方（死代码，且引用了未导入的 `traceback`）。

架构评审（`/private/tmp/architecture-review-2026-07-24.html`，评级 Strong）指出：接口等于实现，删除后复杂度集中而非扩散，通过删除测试。

## Goals / Non-Goals

**Goals:**
- 把错误翻译内联进 `SoulHandler.ui_actions.toggle_mic()`
- 迁移唯一调用方 `commands/pause.py` 直接调用 `self.soul_handler.ui_actions.toggle_mic()`
- 从 `AppController._init_handlers` 移除 `MicManager.initialize()` 及导入
- 删除 `src/ushareiplay/managers/mic_manager.py`

**Non-Goals:**
- 不改变 `commands/mic.py` — 它有自己的 `toggle_mic` 实现，从未使用 `MicManager`
- 不改变错误消息文本（保持 `'Failed to switch to Soul app'` 对外契约不变）
- 不为 `get_mic_status()` 寻找新归宿 — 无调用方的死代码随模块一并删除

## Decisions

### 决策 1: 错误翻译内联进 ui_actions，而非保留消息映射层

**选择**: `ui_actions.toggle_mic()` 直接返回 `{'error': 'Failed to switch to Soul app'}`。

**理由**:
- 这是 `MicManager` 唯一携带的行为，内联后对外契约逐字节不变
- `ui_actions` 的其他方法（如 `send_message`）已经直接返回各自的错误消息，风格一致

### 决策 2: pause.py 通过 BaseCommand 已有的 `self.soul_handler` 访问

**选择**: `self.soul_handler.ui_actions.toggle_mic(...)`，不引入新的管理器属性。

**理由**:
- `BaseCommand.__init__` 已注入 `controller.soul_handler`，`album.py` 等命令已用同一模式
- 局部变量 `mic_toggle = self.soul_handler.ui_actions.toggle_mic` 保持两处调用的可读性

## Risks & Mitigations

**Risk**: 有未发现的 `MicManager` 调用方在运行时动态解析。
**Mitigation**: 全仓 grep `MicManager|mic_manager`（含 tests、config.yaml）确认仅 3 处静态引用；`config.yaml` 无相关配置。

**Risk**: 测试依赖 `MicManager` 单例。
**Mitigation**: 无任何测试文件引用；全量 339 测试通过后提交。

## Testing Decisions

**What makes a good test for this change:**
- 现有测试套件不变即应通过 — 这是行为保持型重构
- `tests/test_dynamic_loading.py` 覆盖命令动态加载，可捕获 pause.py 的导入错误

**Modules to test:**
- `commands/pause.py`（导入与调用路径）
- `core/ui/ui_actions.py`（`toggle_mic` 错误契约）
- `core/app_controller.py`（初始化路径无 `MicManager`）

## Out of Scope

- 重构 `commands/mic.py` 自己的 `toggle_mic` 实现（与 `ui_actions.toggle_mic` 的重复是另一个问题，评审文档未涵盖）
- 统一 `ui_actions` 各方法的错误消息风格
