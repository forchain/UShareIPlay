## 1. 调用点审查

- [x] 1.1 `grep -rn "MicManager\|mic_manager" src/ tests/` 确认全部调用点：`app_controller.py`（初始化）、`commands/pause.py`（唯一业务调用方）
- [x] 1.2 `grep -rn "get_mic_status\|toggle_mic" src/ tests/` 确认 `get_mic_status()` 无调用方、`commands/mic.py` 未使用 `MicManager`
- [x] 1.3 确认 `config.yaml` 无 `mic_manager` 相关配置

## 2. 错误翻译内联进 ui_actions

- [x] 2.1 `ui_actions.toggle_mic()` 的 switch_to_app 失败分支直接返回 `{'error': 'Failed to switch to Soul app'}`
- [x] 2.2 更新 docstring，移除 "retaining MicManager's result contract" 表述

## 3. 迁移调用方

- [x] 3.1 `commands/pause.py`：移除 `MicManager` 导入，改用 `self.soul_handler.ui_actions.toggle_mic(...)`
- [x] 3.2 `app_controller.py`：移除 `MicManager` 导入与 `MicManager.initialize()` 调用

## 4. 删除模块并验证

- [x] 4.1 删除 `src/ushareiplay/managers/mic_manager.py`
- [x] 4.2 `grep -rn "MicManager\|mic_manager" src/ tests/` 确认零残留
- [x] 4.3 全量测试 339/339 通过
