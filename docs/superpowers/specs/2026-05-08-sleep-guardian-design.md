---
covers: [commands, config, sleep-guardian]
created: 2026-05-08
status: draft
---

## 背景与目标

在指定时段内（例如 23:00-06:00，支持跨天），当“睡眠守护模式”开启时，系统**不允许点歌/开始新的播放源**，以避免夜间被用户指令打断休息或引发噪音。

需求约束：
- **默认开启**，且时间窗可配置。
- **除非主动关闭，否则限制一直生效**（跨重启默认恢复为开启）。
- 可通过命令**临时关闭/开启**（进程内生效；重启后回到默认配置）。
- **切歌允许**（`:skip` 允许）。
- `:pause` **允许**。

## 非目标

- 不做跨进程持久化开关（例如写 DB）。本次仅在内存中支持临时切换；重启后使用配置默认值。
- 不做复杂的多时段规则（仅单一 start/end）。

## 术语

- **点歌/开始播放**：任何会“启动播放/开始新的播放源/将新歌加入队列”的命令集合。
- **守护时段**：配置的 `start` 与 `end` 形成的时间窗；若 `start > end` 视为跨天（例如 23:00-06:00）。

## 用户体验

### 被拦截时的提示

当用户在守护时段执行被禁止的点歌类命令时，返回统一错误提示：

- 示例文案（可在实现里作为默认模板，必要时可配置）：
  - `睡眠守护已开启（23:00-06:00），当前时段禁止点歌。如需临时关闭：:sleep off`

### 模式切换命令

新增命令：`:sleep`

- `:sleep on`：开启睡眠守护（临时状态 = on）
- `:sleep off`：关闭睡眠守护（临时状态 = off）
- `:sleep status`：展示当前睡眠守护状态（默认/临时覆盖）、配置的时间窗、以及“此刻是否在守护时段”

备注：
- `:radio sleep` 已存在且含义为 QQ 音乐电台的“疗愈/睡眠频道”。本设计新增的 `:sleep` 是**独立命令前缀**，二者在命令解析层面不冲突（前者的 prefix 是 `radio`，`sleep` 仅作为参数；后者的 prefix 是 `sleep`）。
- 但在“睡眠守护拦截”层面，若 `radio` 被列入 `blocked_commands`，则守护时段内会一并拦截 `:radio <keyword>` 的所有子命令（包括 `:radio sleep`），不会做参数级别的特殊放行。

## 权限与豁免

- 继续沿用现有 `soul.system_users` 逻辑：系统用户（例如机器人/定时器账号）**不受睡眠守护限制**。
  - 现有配置中已包含 `Timer`，因此**定时器触发的命令允许执行**（即使是点歌类命令）。
- `:sleep` 命令本身的等级要求在 `config.yaml -> commands` 中配置（建议设置为 `level: 9` 或 `level: 4`，以避免普通用户随意关闭；最终以产品/运营需求为准）。

## 功能范围：哪些命令会被阻止/允许

### 默认阻止（点歌/开始播放）

以下命令在守护时段 + 守护开启时将被拦截（默认集合，可配置）：
- `play`（立即点歌）
- `next`（加到播放队列）
- `fav`（播放收藏/筛选后播放/收藏搜索播放）
- `singer`（歌手歌单）
- `album`（专辑）
- `playlist`（歌单）
- `radio`（电台）

### 明确允许

- `skip`：允许（切歌）
- `pause`：允许
- `mode`：允许
- `vol`：允许
- 其他非音乐类命令：不受影响

## 技术设计（推荐方案）

### 拦截点

在 `CommandManager.process_command()` 中，在执行 `await command.process(...)` 之前统一检查：

1. `message_info.nickname` 是否为 `soul.system_users`（是则直接放行）
2. 当前命令 `cmd` 是否在 `sleep_guardian.blocked_commands` 中
3. 睡眠守护是否开启：
   - 若存在临时覆盖状态（由 `:sleep on/off` 设置），优先使用覆盖状态
   - 否则使用配置默认值 `sleep_guardian.enabled`
4. 当前时间是否落在守护时段内（依据 `sleep_guardian.start/end`）

满足 2+3+4 时，直接返回错误响应，不进入命令实现层，避免触发 QQ 音乐 UI 操作。

### 状态存储

新增一个轻量的守护状态组件（例如 `SleepGuardianManager` 或 `SleepGuardian`），职责：
- 读取配置（enabled/start/end/blocked_commands）
- 维护**进程内**临时开关覆盖（None/on/off）
- 提供 `should_block(command_prefix, nickname, now)` 与 `format_block_message(...)`

### 配置结构

在 `config.yaml` 增加：

```yaml
sleep_guardian:
  enabled: true
  start: "23:00"
  end: "06:00"
  blocked_commands:
    - play
    - next
    - fav
    - singer
    - album
    - playlist
    - radio
```

同时在 `config.yaml -> commands:` 列表中增加 `sleep` 命令项（`prefix: "sleep"`），并设置合适的 `level` 与模板。

### 边界条件

- `start == end`：视为全天守护（24h 都算在守护时段内）
- 时间解析失败：以安全为先，默认**不阻止**点歌，但在日志里记录配置错误（避免因配置错误导致系统不可用）；实现时需清晰可观测

## 测试计划（单元测试）

无需连接真机/Appium，重点验证拦截逻辑：

- 时间窗判断：
  - 非跨天（例如 09:00-18:00）
  - 跨天（23:00-06:00）
  - `start == end` 全天
- 允许/禁止命令集合生效（`blocked_commands`）
- `system_users` 豁免
- 临时覆盖优先级：
  - 默认 enabled=true，但 `:sleep off` 后放行
  - 默认 enabled=false，但 `:sleep on` 后阻止

