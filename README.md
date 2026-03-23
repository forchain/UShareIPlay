# U Share I Play

Android automation framework that controls the **Soul App** party room and **QQ Music** via Appium. Receives chat commands from room members, plays music, manages seats and timers, and handles room administration — all through a command-driven architecture running on macOS.

## Quick Start

**Requirements**: macOS, Python 3.7+, Android device (ADB), Appium, QQ Music, Soul App.

```bash
# 1. Install dependencies
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure device (copy and edit)
cp config.local.yaml.example config.local.yaml
# → set device.name (ADB address), appium.host/port, soul.default_party_id

# 3. Start Appium (separate terminal)
./appium.sh

# 4. Run
./run.sh
```

> Per-machine settings go in `config.local.yaml` (gitignored). See [docs/config.md](docs/config.md).

## Command Reference

Commands are sent in Soul App room chat as `:prefix [params]`. Access level required is shown (0 = anyone, 9 = owner only).

### Music

| Command | Level | Params | Description |
|---|---|---|---|
| `:play` | 1 | `<song> [artist]` | Play immediately |
| `:next` | 0 | `<song> [artist]` | Add to queue |
| `:fav` | 1 | `[0 language]` | Play favourites |
| `:skip` | 1 | — | Skip current song |
| `:pause` | 1 | `[0/1]` | Pause / resume |
| `:vol` | 1 | `[0-15]` | Set volume (no param = show current) |
| `:mode` | 2 | `0/1/-1` | List / single / random |
| `:acc` | 2 | `[0/1]` | Accompaniment (伴唱) mode |
| `:ktv` | 1 | `[0/1]` | KTV mode (OCR lyrics in chat) |
| `:lyrics` | 1 | — | Post lyrics to chat |
| `:singer` | 1 | `<name>` | Play all songs by artist |
| `:album` | 2 | `<name>` | Play entire album |
| `:playlist` | 2 | `<name>` | Play a playlist |
| `:radio` | 2 | `guess/daily/collection/sleep` | Radio station |
| `:info` | 0 | — | Current song, queue, timers, users |

### Room

| Command | Level | Params | Description |
|---|---|---|---|
| `:theme` | 3 | `<text>` | Set room theme (≤2 chars) |
| `:title` | 3 | `<text>` | Set room title |
| `:topic` | 1 | `<text>` | Set study-room topic |
| `:notice` | 1 | `<message>` | Set announcement |
| `:seat` | 1 | `1 <n> / 2 <n>` | Reserve (1) or take (2) seat n |
| `:mic` | 2 | `0/1` | Microphone off / on |
| `:pack` | 1 | — | Open luck pack |
| `:end` | 4 | — | Close party |
| `:room` | 4 | `<party_id>` | Switch to party |

### Users

| Command | Level | Params | Description |
|---|---|---|---|
| `:admin` | 9 | `1/0 <user>` | Grant / revoke admin |
| `:hello` | 1 | `<user> "<msg>" "<song>"` | Set greeting rule |
| `:say` | 1 | `<message>` | Post message to chat |
| `:keyword` | 1 | `add/del/list <trigger> [resp]` | Keyword auto-reply |
| `:enter` | 1 | `<user> <message>` | Custom enter message |
| `:exit` | 1 | `<user> <message>` | Custom exit message |
| `:return` | 1 | `<user> <message>` | Custom return message |
| `:gift` | 5 | `<user>` | Send gift (yellow duck fallback) |

### Timers

| Command | Level | Params | Description |
|---|---|---|---|
| `:timer add` | 9 | `<key> <HH:MM> <command>` | Add scheduled command |
| `:timer remove` | 9 | `<key>` | Delete timer |
| `:timer list` | 9 | — | List all timers |
| `:timer enable/disable` | 9 | `<key>` | Toggle timer |

### Help

| Command | Level | Description |
|---|---|---|
| `:help` | 0 | Post help text to chat |

## Capability Docs

Detailed reference for the AI agent and contributors:

| Doc | Covers |
|---|---|
| [docs/music.md](docs/music.md) | QQ Music automation, music commands, playback state |
| [docs/room.md](docs/room.md) | Party lifecycle, room customisation, seat management |
| [docs/users.md](docs/users.md) | User levels, greetings, keywords, enter/exit tracking |
| [docs/timers.md](docs/timers.md) | Timer system, DB model, scheduling logic |
| [docs/config.md](docs/config.md) | Config loading, local overrides, structure reference |
| [docs/system.md](docs/system.md) | Architecture, startup flow, singleton pattern, crash recovery |

## Project Structure

```
main.py                  # Entry point
config.yaml              # Master config (26k+ lines)
config.local.yaml        # Per-machine overrides (gitignored)
config.local.yaml.example
src/
  core/                  # AppController, AppHandler, CommandManager, DB, singletons
  handlers/              # SoulHandler, QQMusicHandler
  managers/              # 14+ business logic managers
  commands/              # 30+ command implementations
  models/                # Tortoise ORM models
  dal/                   # Data access objects
  events/                # Background event handlers
data/soul_bot.db         # SQLite database
openspec/                # Change management (proposals, specs, tasks)
docs/                    # Capability reference docs
```
