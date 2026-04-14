## Why

当前系统无法获取 Soul App 的稳定用户 ID，只能从 UI 读取 `username` 并用其 `get_or_create` 生成数据库用户记录。由于 `username` 可被用户随时修改，会导致同一真实用户被创建为多个 `users.id`，从而使基于 `users.id` 绑定的配置（进入/退出/回归事件、关键字、占座等）在改名后失效。

需要引入“别名用户 → 原始用户”的映射，使改名后的用户仍被系统识别为同一原始用户，从而保持既有配置长期有效。

## What Changes

- 在 `users` 表增加一列自关联字段，用于把“别名用户”映射到“原始用户”（canonical）。
- 统一在用户解析入口处做透明归一化：当发现某个用户存在原始用户映射时，后续业务一律以原始用户处理（读取其 `id/level`，并用其 `id` 关联事件、关键字、占座等）。
- 增加一个管理员命令，用于手动建立映射关系：把某个 `username` 绑定为另一个 `username` 的别名。

## Capabilities

### New Capabilities

- `user-canonical-identity`: 支持将可变的 UI 用户名（别名）映射到稳定的“原始用户”身份，并在业务处理中透明归一化到原始用户。

### Modified Capabilities

- （无）

## Impact

- **数据层**：`User` 模型与数据库迁移（`users` 表新增自关联外键列）。
- **DAO/权限与业务归一化**：`UserDAO.get_or_create`（以及任何统一的用户解析入口）需要返回 canonical 用户；影响到依赖该入口的模块（命令权限、关键字、进入/退出/回归事件、占座等）。
- **命令系统**：新增管理员命令与 `config.yaml` 命令配置项。

