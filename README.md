# U Share I Play

<div align="center">

https://github.com/user-attachments/assets/50d9822d-3c32-471e-91fb-8e50892290de

*Demo: Soul App party room automation with QQ Music control via chat commands*

</div>

---

Android automation framework that controls **Soul App** party rooms and **QQ Music** via Appium. Receives chat commands, resolves natural language `@我` mentions via LLM, preserves personalized member memory across sessions, plays music with microphone muting protection, manages party seats and timers, and provides comprehensive room administration — deployable on macOS or Ubuntu Linux with Waydroid virtual audio loopback.

## Quick Start

### Requirements
- **Python**: 3.13+ (managed via [Astral `uv`](https://docs.astral.sh/uv/))
- **Applications**: Soul App, QQ Music
- **Runtime Environment**:
  - **macOS**: Physical Android device or AVD via ADB + Appium 2.x server.
  - **Ubuntu 24.04 LTS (Recommended for VM/Server)**: One-click provisioning via Waydroid container and PipeWire virtual audio routing.

### Option A: Local Development (macOS / Existing Device)

```bash
# 1. Install dependencies
uv sync

# 2. Configure per-machine settings (copy and edit)
cp config.local.yaml.example config.local.yaml
# → set device.name (ADB address), appium.host/port, soul.default_party_id, soul.room_owner

# 3. Start Appium server (in separate terminal)
./appium.sh

# 4. Run bot
./run.sh
# or: uv run ushareiplay
```

### Option B: Ubuntu Linux One-Click Installer (Waydroid Virtual Audio Host)

For headless or virtualized deployments (e.g. Parallels ARM64 VM or Linux server), run the idempotent installer to provision the entire stack:

```bash
bash install.sh
```

This automatically configures:
1. System packages, Node.js, Appium 2.x, and `uiautomator2` driver.
2. Waydroid LineageOS container with QQ Music, Soul App, and Loopback Verifier.
3. PipeWire virtual audio loopback (`ushareiplay_music_sink`) routing music directly into Soul's microphone.
4. Persistent ADB port forwarding (port 5555) and Appium systemd background services.

See [docs/acceptance-one-click-install.md](docs/acceptance-one-click-install.md) and [docs/waydroid-virtual-audio.md](docs/waydroid-virtual-audio.md).

---

## Natural Language & Chat Intake

In addition to standard prefix commands, members can interact naturally by typing `@我 <自然语言>` or `@room_owner <自然语言>` anywhere in the chat:

* **Song Playback**: `@我 帮我放一首周杰伦的晴天` ➔ Resolves to `:play 晴天 周杰伦`
* **Volume Control**: `@我 声音太小了调到10` ➔ Resolves to `:vol 10`
* **Playback Control**: `@我 换一首歌` / `@我 切歌` ➔ Resolves to `:next`
* **Context Awareness**: `@我 再放一遍这首歌` ➔ Replays currently playing song
* **Conversational Reply**: `@我 你好呀` ➔ Natural greeting reply with polite guidance

### Key Capabilities

- **Quoted Message Isolation**: Chat replies containing quoted blocks `「...」` are isolated at intake. Historical quoted text never causes accidental command re-triggers.
- **Dual-Layer User Memory**: Maintains per-user short-term conversation context and long-term memory containing **Immutable Directives** (honorifics, hard constraints) and an **Evolving Profile** (interests, music tastes), distilled in the background without blocking interactive chat.
- **Message Source Tagging**: Outbound messages are tagged to ensure transparency:
  - `[智能]` for AI-generated responses.
  - `[人工]` for backend console operator messages.
- **Playback Muting Protection**: During song changes, the bot automatically mutes its Soul party microphone and adaptively monitors Android `MediaSession` until the new song actively starts playing, preventing noise burps or cut-off transitions.

To enable LLM in `config.local.yaml`:
```yaml
llm:
  enabled: true
  base_url: "https://api.deepseek.com/v1" # or OpenAI, Qwen, Ollama, etc.
  api_key: "sk-your-api-key"
  model: "deepseek-chat"
  timeout: 4.0
```

---

## Command Syntax & Prefixes

Commands can be triggered through several prefixes depending on desired visibility:

- **Public Command (`:` or `：`)**: Standard command. Outputs execution results and announcements to public room chat.
- **Silent Command (`/` or `／`)**: Executes command quietly without broadcasting public chat confirmations.
- **Private Reply (`$` or `＄`)**: Executes command and delivers output directly to the triggering user's private chat.
- **Mention Trigger (`@我` or `@room_owner`)**: Natural language intent resolution via LLM.
- **Chained Queue Grammar**: Multi-command strings separated by `;` (e.g. `:play 晴天; :say 祝大家开心`), supporting `{user_name}` template substitution.

---

## Command Reference

User levels range from `0` (guest / unprivileged) to `9` (owner / system administrator).

### Music Commands

| Command | Level | Params | Description |
|---|---|---|---|
| `:play` | 1 | `<song> [artist]` | Search and play immediately (with mic muting protection) |
| `:next` | 0 | `[<song>] [artist]` | Add song to play queue (no params skips to next queued song) |
| `:fav` | 1 | `[0 language]` | Play favorites; optional language filter (e.g. `:fav 0 粤语`) |
| `:skip` | 1 | — | Skip current song |
| `:pause` | 1 | `[0/1]` | Resume (0) or pause (1); toggles if omitted |
| `:vol` | 1 | `[0-15]` | Set volume (0-15); shows current volume if omitted |
| `:mode` | 2 | `0/1/-1` | Playback mode: `0`=list, `1`=single loop, `-1`=random |
| `:acc` | 2 | `[0/1]` | Toggle accompaniment (伴唱) mode |
| `:lyrics` | 1 | — | Fetch and post current song lyrics to chat |
| `:singer` | 1 | `<name>` | Play top songs by artist |
| `:album` | 2 | `<name>` | Play entire album |
| `:playlist`| 2 | `<name>` | Play a named playlist |
| `:radio` | 2 | `guess/daily/collection/sleep` | Play recommended radio station |
| `:info` | 0 | — | Show current song, queue, online users, and timers |

### Room Commands

| Command | Level | Params | Description |
|---|---|---|---|
| `:theme` | 3 | `<text>` | Set room theme (≤2 chars); combined with title |
| `:title` | 3 | `<text>` | Set room title |
| `:topic` | 1 | `<text>` | Set study-room topic |
| `:notice` | 1 | `<message>` | Set room announcement |
| `:seat` | 1 | `1 <n> / 2 <n> / 4 [n]` | Reserve (1), immediately take (2), or vacate seat occupant (4) |
| `:mic` | 2 | `0/1` | Turn microphone off (0) or on (1); seats bot first if off-seat |
| `:pack` | 1 | — | Open luck pack from backpack (auto-triggered at ≥ 5 online users) |
| `:recommend` | 1 | `[on/off]` | Turn room recommendation distribution on or off |
| `:end` | 4 | — | Close party (requires owner's friend present) |
| `:room` | 4 | `<party_id>` | Switch to a different party room (validates room is open first) |

### User & Automation Commands

| Command | Level | Params | Description |
|---|---|---|---|
| `:level` | 0 | `[<user>] [<0-9>]` | View own/target level, or set user level (requires operator privileges) |
| `:admin` | 9 | `1/0 [<user>]` | Grant (1) or revoke (0) admin role in room UI; defaults to caller if omitted |
| `:alias` | 9 | `"<alias>" "<canonical>"` | Bind alias username to canonical user (maintains ID across renames) |
| `:say` | 1 | `<message>` | Post a message to room chat |
| `:keyword` | 1 | `add/del/list/public/private <trig> [resp]` | Keyword auto-replies with public or private user scope |
| `:enter` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal command to auto-execute when user enters |
| `:exit` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal command to auto-execute when user exits |
| `:return` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal command to auto-execute when user returns |
| `:receive` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal command to auto-execute on receiving gifts/heat |
| `:focus` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal command to auto-execute on study room focus changes |
| `:gift` | 5 | `[<user>]` | Send a gift to user (falls back to yellow duck); defaults to caller |

### System & Scheduling Commands

| Command | Level | Params | Description |
|---|---|---|---|
| `:sleep` | 4 | `on/off/status` | Sleep Guardian: block automated commands during night hours (23:00 - 06:00) |
| `:timer` | 9 | `add <key?> <time> <cmd...> [rep]` | Add scheduled timer (delay in seconds or clock time `HH:MM`) |
| `:timer` | 9 | `remove <key>` | Delete timer |
| `:timer` | 9 | `list` | List all active timers with next trigger times |
| `:timer` | 9 | `enable/disable <key>` | Toggle timer status |
| `:timer` | 9 | `start/stop/reset/reload` | Manage scheduler loop and reload state from DB |
| `:help` | 0 | — | Post command help text to chat |

---

## Documentation & Architecture

Detailed domain documentation and architectural decisions:

| Document | Covers |
|---|---|
| [docs/music.md](docs/music.md) | QQ Music automation, playback muting lifecycle, on-demand filters |
| [docs/room.md](docs/room.md) | Room lifecycle, room name invariant, recommendations, seats & mic |
| [docs/users.md](docs/users.md) | Role policy, levels, enter/exit/receive hooks, dual-layer memory |
| [docs/timers.md](docs/timers.md) | Timer scheduling, queue grammar expansion, SQLite persistence |
| [docs/config.md](docs/config.md) | Configuration loading, merge-by-prefix rules, roles, and overrides |
| [docs/system.md](docs/system.md) | Architecture, state module split, driver lifecycle, chat intake, models |
| [docs/waydroid-virtual-audio.md](docs/waydroid-virtual-audio.md) | Ubuntu Waydroid deployment and PipeWire virtual audio routing |
| [docs/acceptance-one-click-install.md](docs/acceptance-one-click-install.md) | Objective verification checklist for one-click installer |
| [docs/adr/](docs/adr/) | Architecture Decision Records (ADR 0001 - 0008) |

---

## Project Structure

```
install.sh                     # Idempotent Ubuntu one-click installer
main.py                        # Compatibility entry point (prefer: uv run ushareiplay)
pyproject.toml                 # Package configuration (Python >=3.13)
config.yaml                    # Master config template
config.local.yaml              # Per-machine overrides (gitignored)
src/
  ushareiplay/                 # Root Python package
    core/                      # AppController, DriverLifecycle, AppHandler, CommandManager, ChatIntake, RolePolicy
    handlers/                  # SoulHandler, QQMusicHandler
    state/                     # RoomState, PresenceTracker, PlaylistState, PlaybackBroadcaster, OnlineListScraper
    managers/                  # Business logic (Music, RoomName, Seat, Memory, Sleep, Recommendation, etc.)
    commands/                  # 37+ command implementations subclassing BaseCommand
    models/                    # Tortoise ORM models (User, UserMemory, Timer, Events)
    dal/                       # Data access objects (UserDAO, EnterDao, ReceiveDao, etc.)
    events/                    # Background UI event observers
data/soul_bot.db               # SQLite database
docs/                          # Capability documentation and ADRs
tests/                         # Automated pytest test suites
```
