## MODIFIED Requirements

### Requirement: Timer 数据持久化到数据库
系统 SHALL 将所有定时器数据存储在 SQLite 数据库的 `timers` 表中，使用 Tortoise ORM 进行读写，不再依赖 `data/timers.json` 文件。

#### Scenario: 添加定时器（显式 ID）时写入数据库
- **WHEN** 用户执行 `timer add <id> <时间> <消息>` 命令
- **THEN** 系统 SHALL 将新定时器写入数据库，并更新内存缓存，且定时器记录的 `id` SHALL 等于用户提供的 `<id>`

#### Scenario: 添加定时器（省略 ID）时自动生成并写入数据库
- **WHEN** 用户执行 `timer add <时间> <消息>` 命令（未提供 `<id>`）
- **THEN** 系统 SHALL 生成一个随机定时器 ID 并写入数据库与内存缓存，且返回消息/列表中 SHALL 展示该最终 `id`

#### Scenario: 时间为纯数字时按延迟秒数写入数据库
- **WHEN** 用户执行 `timer add <id?> <时间> <消息>` 且 `<时间>` 为纯数字 \(N\)
- **THEN** 系统 SHALL 将该时间解释为延迟 \(N\) 秒执行一次，并将解析后的触发时间（例如 next_trigger）写入数据库与内存缓存

