---
covers: [ConfigLoader, config.yaml, config.local.yaml]
last-synced: 2026-09-23
---

## Overview

All configuration lives in `config.yaml`, which is the committed baseline and the only reference example. `ConfigLoader` loads it at startup and deep-merges an optional local override file `config.local.yaml` (gitignored) for per-machine or per-environment settings.

## Components

| Component | Responsibility |
|---|---|
| `ConfigLoader` | Loads `config.yaml`, deep-merges `config.local.yaml` if present |
| `config.yaml` | Master baseline configuration (device, Appium, Soul App, QQ Music, commands, LLM, roles, sleep) — committed, and doubles as the worked example |
| `config.local.yaml` | Optional per-machine overrides (gitignored); contains only fields that differ from `config.yaml` |

## How It Works

```python
config = ConfigLoader.load_config('config.yaml')
# → loads config.yaml
# → if config.local.yaml exists alongside it, deep-merges onto config
# → returns merged dict
```

### Deep Merge Rules
- **Dictionaries (`dict`)**: Merged recursively. Sub-keys in `config.local.yaml` override or augment base keys without replacing the entire dictionary.
- **Commands List (`commands`)**: Merged by `prefix`. If `config.local.yaml` specifies a command with a matching `prefix`, its fields are merged into that command's configuration rather than overwriting the entire list.
- **Other Lists & Primitives**: Replaced wholesale by local values.

Example: to override only the device address and LLM credentials:
```yaml
# config.local.yaml
device:
  name: "192.168.1.100:5555"

llm:
  enabled: true
  api_key: "sk-your-actual-api-key"
```

## Top-Level Config Structure

| Key | Description |
|---|---|
| `soul` | Soul App package, default party ID, room owner, notice, UI element XPaths, `party_restart_minutes` |
| `qq_music` | QQ Music package, activity, UI element XPaths |
| `commands` | List of command configs: `prefix`, `level`, `subcommands`, `retry`, `response_template`, `error_template` |
| `appium` | `host`, `port` for Appium server connection |
| `device` | `name` (ADB address), `platform_name`, `platform_version`, `automation_name`, `no_reset` |
| `logging` | `directory` for log files |
| `llm` | OpenAI-compatible LLM config: `enabled`, `base_url`, `api_key`, `model`, `timeout`, `system_prompt` |
| `roles` | `room_owner`, `system_users`, `admin_users` |
| `sleep` | Sleep Guardian settings: `enabled`, `start_hour` (23), `end_hour` (6), `blocked_commands` |
| `memory` | Dual-layer user memory settings: `enabled`, `message_threshold`, `timeout` |
| `soul.create_party_recommendation` | Default recommendation state applied when creating a party; the toggle lives in the party settings panel (`soul.elements.party_setting_*`) |

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

- **New top-level section**: Add to `config.yaml`, access via `config['section']['key']` wherever the configuration dictionary is passed.
- **New command override**: Add entry under `commands:` matching the `prefix`; only specify the fields you want to override (e.g. `level: 2`).
- **Secrets & Credentials**: Always place API keys, private tokens, or room credentials in `config.local.yaml` rather than the committed `config.yaml`.
- **Sharing it across worktrees**: `scripts/init_worktree.sh` links each worktree's `config.local.yaml` to the main repository's copy, so per-machine overrides are written once. `run.sh` performs the same link on startup. See `docs/worktree-init.md`.
