---
covers: [ConfigLoader, config.yaml, config.local.yaml, ConfigView, ConfigSectionView, Locator]
last-synced: 2026-11-03
---

## Overview

所有配置都写在 `config.yaml` 里：它是提交进仓库的基线，也是 UI 元素选择器的唯一事实源。
`ConfigLoader` 在启动时读取它，再把可选的 `config.local.yaml`（gitignored）深合并上去，
用于按机器、按环境的差异覆盖。

代码里**正规的**读配置入口只有一个：`core/config_view.py` 里的 `ConfigView` /
`ConfigSectionView` / `Locator`（ADR-0012）。新代码不得再写裸字典下标
`config["soul"]["elements"]` 或 `config.get("soul", {}).get("elements")` 这类形状试探 ——
取的是根配置还是某个应用段，在调用点必须一眼可见。少数尚未迁完的历史调用点仍接受
裸 `dict`（`roles._split_config`、`runtime_logging._logging_directory`、
`command_catalogue.from_config`、`memory_manager.configure`、`sleep_manager`、
`keyword_manager._as_root_view`，以及组合根 `AppController` 的一次性归一化）；
它们只是兼容旧调用方，不是新代码的范例。

本文档只记录 `config.yaml` 里**真实存在且生效**的键；键一律写成从根出发的完整路径
（如 `sleep.start`、`llm.memory.enabled`），以便一眼看出它住在哪一段。

## Components

| Component | Responsibility |
|---|---|
| `ConfigLoader` | 读取 `config.yaml`，深合并 `config.local.yaml`；拒绝本地覆盖元素定义 |
| `ConfigView` / `ConfigSectionView` / `Locator` | 配置读取的唯一入口：根视图、应用段视图、UI 选择器值对象（`src/ushareiplay/core/config_view.py`） |
| `config.yaml` | 主基线配置（设备、Appium、Soul、QQ 音乐、命令、歌词排版、老歌过滤、睡眠、日志、LLM）—— 已提交，同时是配置的唯一样例 |
| `config.local.yaml` | 可选的按机器覆盖（gitignored）；只写与 `config.yaml` 不同的字段，且**不得**包含元素定义 |

## How It Works

```python
from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.config_view import ConfigView

view = ConfigView(ConfigLoader.load_config('config.yaml'))
# → 读取 config.yaml
# → 若同目录存在 config.local.yaml，则深合并上去（元素定义除外，见下）
# → 返回类型化视图；代码里只用视图读配置
```

### Deep Merge Rules
- **Dictionaries (`dict`)**: 递归合并。`config.local.yaml` 的子键就地覆盖或补充基线，不会整块替换。
- **Commands List (`commands`)**: 按 `prefix` 合并。`config.local.yaml` 里写了相同 `prefix` 的命令时，逐字段合并进基线那一条，而不是整表替换。
- **Other Lists & Primitives**: 由本地值整体替换。

Example: to override only the device address and LLM credentials:
```yaml
# config.local.yaml
device:
  name: "192.168.1.100:5555"

llm:
  enabled: true
  api_key: "sk-your-actual-api-key"
```

### Local Override Rules（本地覆盖与元素覆盖策略）

允许在 `config.local.yaml` 中覆盖元素选择器（用于快速应对 App 定位符变更而免于重新发版）。
当 `config.local.yaml` 中存在 `elements`、`risk_elements` 或 `drawer_elements` 覆盖时，
`ConfigLoader` 会照常合并，并输出一条 `WARNING` 日志提醒尽快并入下一个版本的 `config.yaml`。

## Top-Level Config Structure

`config.yaml` 的顶层段**只有**下面十个：

| Key | Description |
|---|---|
| `soul` | Soul App 段：`soul.room_owner`、`soul.package_name`、`soul.launcher_packages`、`soul.unknown_page_force_close_threshold`、`soul.chat_activity`、`soul.default_party_id`、`soul.default_notice`、`soul.default_theme`、`soul.default_title`、`soul.broadcast_playing_info`、`soul.playback_mute.*`、`soul.admin_users`、`soul.system_users`、`soul.system_default_notices`、`soul.party_restart_minutes`、`soul.party_create_mode`、`soul.create_party_recommendation`、`soul.change_party_type`、`soul.post_party_create.*`、`soul.risk_elements`、`soul.drawer_elements`、`soul.elements` |
| `qq_music` | QQ 音乐段：`qq_music.package_name`、`qq_music.search_activity`、`qq_music.tab_max_swipes`、`qq_music.elements` |
| `lyrics` | 歌词排版：`lyrics.line_max_width` |
| `commands` | 命令表（38 条）。每条命令可含 `prefix`、`level`、`subcommands`、`guest_allowed`、`description`、`help`、`help_order`、`retry`、`response_template`、`error_template` |
| `old_song_filter` | 老歌过滤：`old_song_filter.enabled`、`old_song_filter.cutoff_date`、`old_song_filter.radio_max_refreshes`、`old_song_filter.artist_whitelist` |
| `sleep` | 睡眠守卫：`sleep.enabled`、`sleep.start`、`sleep.end`、`sleep.blocked_commands` |
| `appium` | Appium server 连接：`appium.host`、`appium.port` |
| `logging` | 日志目录：`logging.directory` |
| `device` | 设备：`device.name`（ADB 地址）、`device.platform_name`、`device.platform_version`、`device.automation_name`、`device.no_reset` |
| `llm` | OpenAI 兼容协议的 LLM 配置：`llm.enabled`、`llm.base_url`、`llm.api_key`、`llm.model`、`llm.timeout`、`llm.system_prompt`、`llm.memory.*` |

### soul（角色与房主配置都在这一段）

| Key | Description |
|---|---|
| `soul.room_owner` | 房主昵称。后台操作以房主身份执行；角色判定的事实源（ADR-0008） |
| `soul.admin_users` | 人工管理员昵称列表（房主天然具备管理员身份） |
| `soul.system_users` | 系统自动化角色昵称列表（如 `Timer`、`Agent`） |
| `soul.package_name` / `soul.chat_activity` | Soul 包名与聊天 Activity，用于拉起 App |
| `soul.launcher_packages` | 判定「Soul 不在前台」时用来切回桌面用的包名列表 |
| `soul.unknown_page_force_close_threshold` | 连续 N 次返回键仍未能退出未知页面时，强制关闭 Soul 应用以恢复；取值须 >= 1（默认 10） |
| `soul.default_party_id` | 默认派对房间 ID |
| `soul.default_notice` / `soul.default_theme` / `soul.default_title` | 默认公告 / 主题 / 标题 |
| `soul.broadcast_playing_info` | 是否把当前播放信息播报到公屏 |
| `soul.playback_mute.enabled` / `soul.playback_mute.guest_room_only` / `soul.playback_mute.auto_enable_on_mic` / `soul.playback_mute.ignore_users` / `soul.playback_mute.timeout` / `soul.playback_mute.settling_delay` | 播放静音保护（ADR-0007）：切歌期间闭麦，就绪后再开麦 |
| `soul.system_default_notices` | 系统重置后的默认公告特征串列表 |
| `soul.party_restart_minutes` | 触发派对智能重启的时间（分钟） |
| `soul.party_create_mode` | 派对创建模式，取值 `new_party_entry`（新建）或 `restore_party`（恢复） |
| `soul.create_party_recommendation` | 创建派对时是否开启推荐；开关本体在派对设置面板（`soul.elements.party_setting_*`） |
| `soul.change_party_type` | 创建派对时是否切换派对类型 |
| `soul.post_party_create.enabled` / `soul.post_party_create.wait_for_command_ready` / `soul.post_party_create.commands` | 新建派对成功后的自动化（仅投递命令到 MessageQueue） |
| `soul.risk_elements` | 风险元素 key 列表（关弹窗、收起面板等自动处理） |
| `soul.drawer_elements` | 抽屉式弹窗 key 列表（检测到即自动关闭） |
| `soul.elements` | UI 元素选择器映射（203 项），**唯一事实源** |

`soul.risk_elements` / `soul.drawer_elements` 里写的每个 key 都必须在 `soul.elements`
里有对应选择器，否则机器人永远找不到它；留空（`[]`）或删除本项会回退到事件层的默认列表。

### qq_music

| Key | Description |
|---|---|
| `qq_music.package_name` / `qq_music.search_activity` | QQ 音乐包名与搜索 Activity |
| `qq_music.tab_max_swipes` | 首页 tab 横滑查找的上限 |
| `qq_music.elements` | UI 元素选择器映射（84 项），**唯一事实源** |

### lyrics

| Key | Description |
|---|---|
| `lyrics.line_max_width` | 歌词发到公屏前单行的最大长度，超出则拆行（优先在空格处换行） |

### old_song_filter

| Key | Description |
|---|---|
| `old_song_filter.enabled` | 是否启用老歌过滤 |
| `old_song_filter.cutoff_date` | 老歌判定的时间截止点 |
| `old_song_filter.radio_max_refreshes` | 电台推荐连续刷新的次数上限 |
| `old_song_filter.artist_whitelist` | 歌手白名单（不受老歌过滤影响） |

### sleep

| Key | Description |
|---|---|
| `sleep.enabled` | 是否启用睡眠守卫 |
| `sleep.start` / `sleep.end` | 睡眠时段，**`HH:MM` 字符串**（如 `"23:00"` / `"06:00"`），不是小时数 |
| `sleep.blocked_commands` | 睡眠时段拦截的命令前缀列表 |

### llm 与记忆配置

| Key | Description |
|---|---|
| `llm.enabled` | 是否启用大模型自然语言命令解析 |
| `llm.base_url` / `llm.api_key` / `llm.model` | OpenAI 兼容接口的地址、密钥、模型名 |
| `llm.timeout` | 自然语言解析超时（秒） |
| `llm.system_prompt` | 自定义系统提示词 / 人设补充（可为空） |
| `llm.memory.enabled` | 是否启用用户个性化记忆系统 |
| `llm.memory.min_messages` | 触发记忆提炼所需的最小未整理消息数 |
| `llm.memory.min_level_for_long_term` | 允许写入长期记忆的最低权限等级 |
| `llm.memory.worker_delay_seconds` | 记忆后台任务的延迟（秒） |
| `llm.memory.timeout` | 异步记忆提炼的 LLM 超时（秒） |

记忆相关配置住在 `llm.memory` 之下，**不在**顶层。

## Config View / Locator（代码里读配置的唯一入口）

`core/config_view.py` 提供三个东西：根视图 `ConfigView`、应用段视图 `ConfigSectionView`、
UI 选择器值对象 `Locator`。它们继承自 `object` 而不是 `dict` —— 视图**不是**字典，
没有 `view[...]` 下标，也没有 `view.get(...)`。

### 根视图 ConfigView

| API | 说明 |
|---|---|
| `config.soul` | Soul App 段视图（`ConfigSectionView`） |
| `config.music` | QQ 音乐段视图（`ConfigSectionView`） |
| `config.section(name)` | 取顶层段视图；段不存在抛 `MissingConfigSection` |
| `config.maybe_section(name)` | 取顶层段视图；段不存在返回 `None` |
| `config.value(key, default=None)` | 根级参数；缺失返回 `default` |
| `config.require(key)` | 根级必需参数；缺失抛 `MissingConfigKey` |
| `config.command_entries` | 根级命令表（`commands` 列表） |
| `config.data` | 底层根映射（逃生舱，只读用途） |
| `config.reload(new_mapping)` | 原地热重载（见下） |
| `config.validate_required_elements()` | 启动期必需元素校验（见下） |

```python
view.soul.value("party_restart_minutes", 720)   # 段内参数，带兜底
view.music.element("search_entry")               # UI 选择器
view.section("appium").require("host")          # 根级段的必需参数
view.command_entries                             # 命令表
```

### 段视图 ConfigSectionView

`SoulHandler.config` 与 `QQMusicHandler.config` 就是段视图（组合根注入，见
[ADR-0009](adr/0009-composition-root-dependency-injection-and-singleton-contract.md)）。

| API | 说明 |
|---|---|
| `section.name` | 段名（`soul` / `qq_music` / 嵌套段名） |
| `section.element(key)` | 必需的元素选择器 → `Locator`；缺失抛 `MissingElementKey` |
| `section.maybe_element(key)` | 可选的元素选择器 → `Locator` 或 `None` |
| `section.value(key, default=None)` | 段内参数；缺失返回 `default` |
| `section.require(key)` | 段内必需参数；缺失抛 `MissingConfigKey` |
| `section.section(key)` | 嵌套子段视图；同一子段名恒返回同一实例（重载后身份与内容都保持最新）；缺失抛 `MissingConfigKey` |
| `section.maybe_section(key)` | 嵌套子段视图；同一子段名恒返回同一实例（重载后身份与内容都保持最新）；缺失返回 `None` |
| `section.data` | 底层映射（逃生舱，只读用途） |

```python
section = view.soul
section.element("message_content")                            # Locator
section.value("party_restart_minutes", 720)                    # 段内参数
section.section("playback_mute").value("timeout", 5.0)         # 嵌套段
section.maybe_element("seat_invite_panel")                     # 可选选择器
```

### Locator（选择器值对象）

`Locator` 把「这条选择器是什么」这件事收敛到一个地方：XPath 与 resource-id 的判定规则
此前在 `element_finder`、`event_manager`、`gesture_handler`、`seat_panel_driver` 四处
各写了一遍。

| API | 说明 |
|---|---|
| `Locator.from_value(value)` | 由选择器字符串构造；以 `//` 或 `./` 开头算 XPath，其余算 resource-id |
| `locator.kind` | `"xpath"` 或 `"id"` |
| `locator.value` | 原始选择器字符串 |
| `locator.appium` | Appium 定位元组 `(by, value)`：`AppiumBy.XPATH` 或 `AppiumBy.ID` |
| `locator.absolute_xpath` | 绝对 XPath：id → `//*[@resource-id='<value>']`；xpath → 原值 |
| `locator.relative_xpath` | 相对子节点 XPath：id → `.//*[@resource-id='<value>']`；xpath → `"." + value`（本身以 `.` 开头则原样返回） |
| `locator.matches(node)` | 判断某个已解析 XML 节点是不是本选择器指向的元素（id 认得带包名前缀的形式） |

```python
locator = view.soul.element("message_content")
by, value = locator.appium
locator.absolute_xpath
locator.relative_xpath
```

### 异常层级

`ConfigError` 是配置读取失败的基类，下面分三支：`MissingConfigSection`（段不存在）、
`MissingConfigKey`（段内必需键缺失）、`MissingElementKey`（元素选择器缺失）。

### 启动期失败前置校验

组合根 `AppController` 在构造时调用 `config.validate_required_elements()`：启动期必需的
元素选择器缺任何一项，当场抛 `MissingElementKey`，机器人起不来 —— 而不是等到运行期
操作 UI 时才炸在某个无关的报错上。

必需集合定义在 `core/config_view.py` 的 `REQUIRED_ELEMENTS`：

- `soul` 段：消息读取与回复相关的 `message_content`、`message_list`、`input_box`、
  `button_send`、`message_reply_view`、`message_reply_content`；
  座位面板的 `seat_desk`、`left_seat`、`right_seat`、`left_state`、`right_state`、
  `left_label`、`right_label`、`left_default_name`、`right_default_name`、
  `left_avatar`、`right_avatar`、`left_rank`、`right_rank`
- `qq_music` 段：`search_entry`

配置错误（`ConfigError` 或 `config.local.yaml` 覆盖元素定义）在 `__main__.main()`
里是**致命**的：打印出错段与键后以退出码 2 退出，不进入重启循环 —— 否则一次配置
漏项会变成十条相同的崩溃日志，还会被 systemd / docker 当成正常停止。

### 热重载

`config.reload(new_mapping)` **原地**改写底层映射：根映射、视图实例、已经发出去的段视图
（含嵌套段视图）实例，对象身份都不变。因此长生命周期的 Handler / Manager 单例不需要重新
接线就能看到新配置。新映射里不存在的段会从根映射移除，其旧视图被清空，不再端着过期配置。
`ConfigReloadManager` 走的正是这条路，并在写活配置前用
`ConfigView.validate_required_elements()` 跑**同一份**必需清单：会拒绝任何「重启也起不来」
的新配置，而不是接受之后在下一次启动时炸掉。

## Common Local Overrides

```yaml
# config.local.yaml — only write fields that differ from defaults

device:
  name: "192.168.8.105:5555"      # ADB address (physical device or VM)

appium:
  host: "127.0.0.1"
  port: 4723

soul:
  default_party_id: "FM00000000"   # Target Soul party room ID
  room_owner: "YourSoulNickname"   # Backend room owner identity

llm:
  enabled: true
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-xxx"
  model: "deepseek-chat"
```

## Command Levels

每条命令的 `guest_allowed` 决定他人房间（客房模式）是否可用；`help` / `help_order`
提供 `:help` 文案与排序；`sleep.blocked_commands` 决定睡眠时段拦截哪些前缀。
启动时 `CommandCatalogue` 会校验每个声明的前缀都能在 `ushareiplay/commands/` 下
找到对应的 `BaseCommand` 模块，缺失或前缀重复会直接启动失败。

每个命令的顶层 `level` 是该命令的兜底门槛。`subcommands` 用来给同一条命令的
不同调用形态配不同门槛：只读形态放低，能改状态的形态放高。

```yaml
- prefix: "playlist"
  level: 2                      # 兜底门槛
  subcommands:
    '':
      level: 1                  # 无参调用：只读当前播放队列
    '*':
      level: 2                  # 其余带参调用：切歌单
```

匹配顺序：

1. 无参调用命中 `''`（空参数）；该形态没写等级时回退顶层 `level`；
2. 首参数（忽略大小写）命中同名子命令，如 `list`；该子命令没写等级时依次
   尝试 `'*'` 规则、顶层 `level`；
3. 其余带参调用命中 `'*'`；没写等级时回退顶层 `level`；
4. 都没命中，回退顶层 `level`（默认 1）。

子命令配置写成字典是为了给后续属性（描述、是否静默等）留位置；写整数标量
（如 `list: 1`）也等价于 `list: {level: 1}`，字符串不是等级写法。

等级判定只有一处事实源：`src/ushareiplay/core/roles.py` 的
`resolve_command_level`（门禁用）与 `min_command_level`（自然语言提示用，
取所有形态里的最低等级，与门禁口径一致）。

## Extension Points

- **New top-level section**: Add to `config.yaml`，然后用 `config.section("name")` 取段视图、用 `.value()` / `.require()` 读键 —— 不要把裸字典继续往下传。
- **New UI element**: 只在 `config.yaml` 的 `soul.elements` / `qq_music.elements` 里加一条选择器，代码侧统一用 `section.element("key")` 取；`config.local.yaml` 不允许覆盖元素定义。
- **New command override**: Add entry under `commands:` matching the `prefix`; only specify the fields you want to override (e.g. `level: 2`).
- **Secrets & Credentials**: Always place API keys, private tokens, or room credentials in `config.local.yaml` rather than the committed `config.yaml`.
- **Sharing it across worktrees**: `scripts/init_worktree.sh` links each worktree's `config.local.yaml` to the main repository's copy, so per-machine overrides are written once. `run.sh` performs the same link on startup. See `docs/worktree-init.md`.
