---
covers: [ConfigLoader, config.yaml, config.local.yaml]
last-synced: 2026-09-23
---

## Overview

All configuration lives in `config.yaml`. `ConfigLoader` loads it at startup and deep-merges a local override file `config.local.yaml` (gitignored) for per-machine or per-environment settings.

## Components

| Component | Responsibility |
|---|---|
| `ConfigLoader` | Loads `config.yaml`, deep-merges `config.local.yaml` if present |
| `config.yaml` | Master configuration template (device, Appium, Soul App, QQ Music, commands, LLM, roles, sleep) |
| `config.local.yaml` | Per-machine overrides (gitignored); contains only fields that differ from defaults |
| `config.local.yaml.example` | Template demonstrating common override patterns |

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
| `commands` | List of command configs: `prefix`, `level`, `retry`, `response_template`, `error_template` |
| `appium` | `host`, `port` for Appium server connection |
| `device` | `name` (ADB address), `platform_name`, `platform_version`, `automation_name`, `no_reset` |
| `logging` | `directory` for log files |
| `llm` | OpenAI-compatible LLM config: `enabled`, `base_url`, `api_key`, `model`, `timeout`, `system_prompt` |
| `roles` | `room_owner`, `system_users`, `admin_users` |
| `sleep` | Sleep Guardian settings: `enabled`, `start_hour` (23), `end_hour` (6), `blocked_commands` |
| `memory` | Dual-layer user memory settings: `enabled`, `message_threshold`, `timeout` |
| `recommendation`| Party recommendation auto-sync and drawer settings |

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

## Extension Points

- **New top-level section**: Add to `config.yaml`, access via `config['section']['key']` wherever the configuration dictionary is passed.
- **New command override**: Add entry under `commands:` matching the `prefix`; only specify the fields you want to override (e.g. `level: 2`).
- **Secrets & Credentials**: Always place API keys, private tokens, or room credentials in `config.local.yaml` rather than the committed `config.yaml`.
