## 1. ConfigLoader 深度合并实现

- [x] 1.1 在 `src/core/config_loader.py` 中实现 `_deep_merge(base, override)` 递归合并函数
- [x] 1.2 修改 `load_config()` 推导本地配置路径（同目录下 `config.local.yaml`）
- [x] 1.3 若本地文件存在且非空，调用 `_deep_merge` 合并到主配置后返回

## 2. 版本控制排除

- [x] 2.1 在 `.gitignore` 中添加 `config.local.yaml` 条目

## 3. 示例文件

- [x] 3.1 在项目根目录创建 `config.local.yaml.example`，包含 `device.name`、`appium.host`/`port`、`soul.default_party_id` 等常用覆盖示例（使用占位符值）
