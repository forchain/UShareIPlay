## Context

当前 `ConfigLoader.load_config()` 仅加载单一 `config.yaml`（7行，极简实现）。`config.yaml` 超过 26000 行，包含设备地址、Appium host/port、派对 ID、UI 元素 XPath、命令模板等所有配置。开发机和生产机差异字段（如 `device.name`、`appium.host`、`soul.default_party_id`）当前通过注释切换，易误提交。

## Goals / Non-Goals

**Goals:**
- 支持 `config.local.yaml` 作为本地覆盖文件，深度合并到主配置
- 文件不存在时行为与现在完全一致（零破坏性）
- `.gitignore` 排除 `config.local.yaml`
- 提供 `config.local.yaml.example` 展示常用覆盖场景

**Non-Goals:**
- 不支持环境变量覆盖（超出本次范围）
- 不支持多级 local 文件（如 `config.local.dev.yaml`）
- 不改变 `config.yaml` 的结构或内容

## Decisions

### 深度合并而非浅合并

**选择**：递归深度合并（dict 逐层覆盖，非 dict 值直接替换）
**原因**：`config.yaml` 是嵌套结构（`soul.elements.*`、`commands[*]`），浅合并会丢失未覆盖的子键。例如只想覆盖 `device.name`，不能丢掉 `device` 下其他字段。
**替代方案**：`dict.update()`（浅合并）— 拒绝，会导致整个顶级 key 被替换。

### 本地文件路径与主配置同目录

**选择**：`config.local.yaml` 路径 = 主配置路径替换后缀，即 `config_path` 对应的 `config.local.yaml`
**原因**：`load_config()` 已接受 `config_path` 参数，保持一致性；测试时可传入临时路径。
**替代方案**：硬编码路径 — 拒绝，降低可测试性。

### 加载顺序：先主配置，再本地覆盖

主配置提供完整默认值（生产环境），本地文件仅声明差异。这样生产环境不需要本地文件，开发环境只写少量覆盖即可。

## Risks / Trade-offs

- **列表合并语义不明确** → 对 `commands` 等列表字段，深度合并选择**直接替换整个列表**（非按索引合并），因为列表元素无稳定 key。若需覆盖单个命令模板，需在本地文件中复制整个列表——可接受，因覆盖命令模板的场景极少。
- **敏感信息风险** → `config.local.yaml.example` 中不写真实值，仅写占位符，README 说明不要提交该文件。

## Migration Plan

1. 修改 `ConfigLoader.load_config()`，加入深度合并逻辑
2. 在 `.gitignore` 追加 `config.local.yaml`
3. 新增 `config.local.yaml.example`
4. 无需数据迁移；无需重启以外的部署步骤

**Rollback**：删除新增的合并逻辑即可，`config.yaml` 不受影响。

## Open Questions

- 无
