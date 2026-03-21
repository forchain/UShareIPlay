## ADDED Requirements

### Requirement: Timer 数据持久化到数据库
系统 SHALL 将所有定时器数据存储在 SQLite 数据库的 `timers` 表中，使用 Tortoise ORM 进行读写，不再依赖 `data/timers.json` 文件。

#### Scenario: 添加定时器时写入数据库
- **WHEN** 用户执行 `timer add <id> <时间> <消息>` 命令
- **THEN** 系统 SHALL 将新定时器写入数据库，并更新内存缓存

#### Scenario: 删除定时器时从数据库移除
- **WHEN** 用户执行 `timer remove <id>` 命令
- **THEN** 系统 SHALL 从数据库删除对应记录，并从内存缓存移除

#### Scenario: 定时器触发后更新下次触发时间
- **WHEN** 一个 repeat=True 的定时器被触发
- **THEN** 系统 SHALL 将 next_trigger 更新为次日同一时间，并将更新写入数据库

#### Scenario: 一次性定时器触发后在数据库中禁用
- **WHEN** 一个 repeat=False 的定时器被触发
- **THEN** 系统 SHALL 将该定时器的 enabled 字段在数据库中置为 False

### Requirement: 启动时从数据库加载定时器
系统 SHALL 在 TimerManager 启动时从数据库加载所有定时器到内存缓存，不再读取 `config.yaml` 的 `initial_timers` 段。

#### Scenario: 正常启动加载数据库中的定时器
- **WHEN** TimerManager.start() 被调用且数据库中有定时器记录
- **THEN** 系统 SHALL 将所有数据库中的定时器加载到 `_timers` 内存字典

#### Scenario: 数据库为空时无定时器加载
- **WHEN** TimerManager.start() 被调用且数据库 timers 表为空
- **THEN** 系统 SHALL 以空的 `_timers` 字典启动，不报错

### Requirement: 首次运行时从 timers.json 迁移数据
系统 SHALL 在数据库 timers 表为空时，自动检测并导入现有的 `data/timers.json` 文件中的定时器数据。

#### Scenario: 首次部署时自动迁移
- **WHEN** TimerManager 首次启动，数据库 timers 表为空，且 `data/timers.json` 存在
- **THEN** 系统 SHALL 将 timers.json 中所有有效定时器记录导入数据库，并记录迁移日志

#### Scenario: 无 timers.json 时跳过迁移
- **WHEN** TimerManager 首次启动，数据库 timers 表为空，且 `data/timers.json` 不存在
- **THEN** 系统 SHALL 以空定时器列表正常启动，不报错

#### Scenario: 数据库已有数据时不再读取 timers.json
- **WHEN** TimerManager 启动，数据库 timers 表中已有记录
- **THEN** 系统 SHALL 直接从数据库加载，忽略 `data/timers.json`（即使文件存在）

### Requirement: timer reload 命令强制从数据库同步内存缓存
系统 SHALL 提供 `timer reload` 命令，重新从数据库读取所有定时器数据并覆盖内存缓存，使直接修改数据库的变更立即生效。

#### Scenario: 直接修改数据库后执行 reload
- **WHEN** 用户直接修改了数据库中的定时器记录，然后执行 `timer reload`
- **THEN** 系统 SHALL 重新加载数据库中的所有定时器到内存，并返回加载的定时器数量

#### Scenario: reload 后定时器按最新 DB 数据运行
- **WHEN** `timer reload` 执行完成
- **THEN** `timer list` SHALL 显示与数据库一致的定时器列表，运行中的触发逻辑使用最新数据

### Requirement: 移除 config.yaml 的 initial_timers 配置
系统 SHALL 不再从 `config.yaml` 的 `initial_timers` 段读取定时器种子数据，该配置段 SHALL 被完全删除。

#### Scenario: 启动时不读取 config.yaml 中的定时器配置
- **WHEN** 系统启动
- **THEN** TimerManager SHALL 不访问 config 中的 `initial_timers` 字段，也不执行 `load_initial_timers()` 调用
