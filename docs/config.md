---
covers: [ConfigLoader, config.yaml, config.local.yaml]
last-synced: 2026-03-23
---

## Overview

All configuration lives in `config.yaml`. `ConfigLoader` loads it at startup and optionally deep-merges a local override file `config.local.yaml` (not tracked in git) for per-machine settings.

## Components

| Component | Responsibility |
|---|---|
| `ConfigLoader` | Loads `config.yaml`, deep-merges `config.local.yaml` if present |
| `config.yaml` | Master config: device, Appium, Soul App, QQ Music, commands, logging |
| `config.local.yaml` | Per-machine overrides (gitignored); only fields that differ from defaults |
| `config.local.yaml.example` | Template showing common override fields |

## How It Works

```python
config = ConfigLoader.load_config('config.yaml')
# → loads config.yaml
# → if config.local.yaml exists alongside it, deep-merges onto config
# → returns merged dict
```

**Deep merge rules**:
- `dict` values: merged recursively (only specified sub-keys overridden)
- All other types (str, int, list): local value replaces entirely
- Lists are **replaced wholesale** — no element-level merging

Example: to override only the device address without affecting other `device` fields:
```yaml
# config.local.yaml
device:
  name: "192.168.1.100:5555"
```

## Top-level Config Structure

| Key | Description |
|---|---|
| `soul` | Soul App package, party ID, notice, system users, UI element XPaths, `party_restart_minutes` |
| `qq_music` | QQ Music package, activity, UI element XPaths |
| `commands` | List of command configs: `prefix`, `level`, `response_template`, `error_template` |
| `appium` | `host`, `port` for Appium server connection |
| `device` | `name` (ADB address), `platform_name`, `platform_version`, `automation_name`, `no_reset` |
| `logging` | `directory` for log files |

## Common Local Overrides

```yaml
# config.local.yaml — only write fields that differ from config.yaml defaults

device:
  name: "192.168.x.x:5555"      # your device ADB address

appium:
  host: "localhost"               # local Appium server
  port: 4723

soul:
  default_party_id: "FM00000000" # dev/test party room
```

## Extension Points

- **New top-level section**: Add to `config.yaml`, access via `config['section']['key']` anywhere a handler/manager receives the config dict.
- **New command config**: Add entry under `commands:` list with `prefix`, `level`, `response_template`, `error_template`.
- **Sensitive values**: Put them in `config.local.yaml` (gitignored) rather than `config.yaml`.
