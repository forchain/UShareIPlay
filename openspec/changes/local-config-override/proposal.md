## Why

`config.yaml` 是单一配置文件，开发环境和生产环境使用不同的设备地址、Appium 服务器、派对 ID 等参数时，需要手动切换或维护多个分支，容易出错且难以管理。增加一个优先级更高的本地配置文件 `config.local.yaml`，不纳入版本控制，让每个环境自行维护差异配置，主配置保持生产环境默认值。

## What Changes

- 新增 `config.local.yaml` 支持：启动时若该文件存在则加载，并对 `config.yaml` 的对应字段进行深度合并覆盖
- `ConfigLoader` 增加本地文件合并逻辑（深度合并，局部覆盖）
- `.gitignore` 增加 `config.local.yaml` 排除规则
- 新增 `config.local.yaml.example` 示例文件，展示常用覆盖场景（设备地址、Appium host、派对 ID 等）

## Capabilities

### New Capabilities

- `local-config`: 支持 `config.local.yaml` 本地覆盖配置文件，深度合并到主配置，不纳入版本控制

### Modified Capabilities

<!-- 无现有 spec 需要修改 -->

## Impact

- `src/config_loader.py`（或等效的配置加载模块）：增加本地文件检测与深度合并逻辑
- `.gitignore`：排除 `config.local.yaml`
- 新增文件：`config.local.yaml.example`
- 对现有功能零破坏性影响：本地文件不存在时行为与当前完全一致
