---
covers: [UserManager, AdminManager, MessageManager, KeywordManager, MemoryManager, RolePolicy, UserDAO, EnterDao, ExitDao, ReturnDao, ReceiveDao, FocusEventDao, AdminCommand, AliasCommand, SayCommand, KeywordCommand, EnterCommand, ExitCommand, ReturnCommand, ReceiveCommand, FocusCommand, GiftCommand, LevelCommand]
last-synced: 2026-09-23
---

## Overview

User management handles identity, role hierarchy, permission levels, automated greetings, keyword-triggered responses, event-driven command hooks (enter, exit, return, receive, focus), and dual-layer user memory. `UserManager` and `UserDAO` manage user levels and aliases, `RolePolicy` enforces operator and permission tiers, while `MemoryManager` persists conversational preferences.

## Canonical Identity (Username Aliases)

Soul UI only exposes a mutable display name (`username`). When a user renames themselves, the system could otherwise create a duplicate `User` row, breaking any configuration bound to the original `users.id` (enter/exit/return events, private keywords, seat reservations, user memory, and permission level checks).

To keep ID-bound behavior stable across renames, the DB maps an alias user to a canonical (original) user via `users.canonical_user_id`. The system resolves alias usernames to their canonical user during normal processing.

**Admin command**:
- `:alias "<alias>" "<canonical>"` (level 9): bind an alias username to a canonical username.

### 两个命名域：用户名参数必须按域解析

同一个人同时有两个名字，而且它们是不相同的字符串：

- **可见昵称（分身名）** — Soul UI 唯一渲染出来的名字：座位头像卡片、在线列表、聊天行、私聊入口都按它找人。分身（小号）与主账号在 UI 上是两个可见昵称。
- **canonical 名（主账号名）** — `UserDAO.get_or_create` 把任意别名解析后的规范记录名；所有 ID 绑定的配置（enter/exit/return/receive/focus 钩子、座位预约、私有关键词、用户记忆、等级）都挂在它上面。

**规则**：任何以用户名作参数的命令，DB 侧继续用 canonical，**面向 Soul UI 的查找必须先解析成当前可见昵称**；跨命名域的比对必须按身份判定，禁止 `==` 字符串相等。把 canonical 名直接拿去和 UI 文本比较必然永不相等 —— 这就是 `:seat 3` 在专注钩子里报 `User <主账号名> not found on any seat`（2026-09-30）的根因。

可用接缝（`src/ushareiplay/`）：

| 接缝 | 用途 |
|---|---|
| `UserDAO.get_identity_usernames(name)` | 同一身份（主账号 + 全部分身）的昵称集合，**不写库**，陌生名字不会建记录 |
| `UserDAO.is_same_identity(requested, observed)` | 调用方给的名字与 UI 读到的名字是否同一人（座位弹窗、卡片证据等逐条比对） |
| `InfoManager.resolve_visible_username(name)` | 解析成房间里当前可见的分身名（在线列表、资料页、座位靶子） |
| `InfoManager.is_user_or_avatar_online(name)` | 任意分身在线即视为在线 |

已按此规则接线的用户名参数入口：`:seat 3 [user]`（命令层解析可见名 + 座位层按身份匹配）、`:admin 1|0 [user]`（在线列表按可见名打开资料页，房间管理员也以可见名记账，供座位观测与 `:info` 比对）、`:gift [user]`、Seat Event Hooks 的 `{seat}`/`{action}` 取值（观测键是分身名）。

纯 DB 侧的入口无需额外解析，`UserDAO` 的 canonical 解析已经保证同一身份：`:level [user] [n]`、`:enter/:exit/:return/:receive/:focus add`、`:alias`。

## Components

| Component | Responsibility |
|---|---|
| `UserManager` | User lookup, level assignment, gift dispatch, persistence via `UserDAO` |
| `RolePolicy` | Evaluates caller tiers: Human Operators, System Users, Privileged Users, Normal Users |
| `MemoryManager` | Dual-layer user memory: short-term interaction window + long-term profile / immutable directives |
| `AdminManager` | Toggles in-app admin role for users in Soul App party room UI |
| `MessageManager` | Outbound message queue dispatch; parses entry notifications and triggers automated actions |
| `KeywordManager` | Maps trigger keywords → response messages (public or private scope, stored in DB) |
| `UserDAO` | CRUD and canonical alias resolution for `User` model |
| `EnterDao` / `ExitDao` / `ReturnDao` | Configures and triggers user-defined command hooks for enter, exit, and return events |
| `ReceiveDao` | Configures and triggers user-defined command hooks when gifts or heat contributions are received |
| `FocusEventDao` | Configures and triggers user-defined command hooks on study room focus count changes |

## How It Works

### Role Hierarchy & User Levels
`RolePolicy` checks permission before command dispatch:
- **Human Operators** (Host/Owner `soul.room_owner`, `Console`, and in-app room admins): bypass user level limits and can bypass late-night Sleep Guardian.
- **System Users** (`Timer`, `Agent`, `System`): automated internal actors, bypass level checks.
- **Normal Users**: require database `user.level >= command.level`. Unknown users default to level 0.

```
Level  Role
  0    Guest (playback requests, :info, :level query, :help)
  1    Regular user (:vol, :fav, :skip, :lyrics, :say, :keyword, :enter, :exit, :return, :receive, :focus, :seat, :pack, :recommend)
  2    Trusted user (:mode, :acc, :playlist, :album, :radio, :mic)
  3    VIP (:theme, :title)
  4    Moderator (:end room, :sleep override)
  5    Sub-admin (:gift)
  9    Owner / Admin (:admin, :alias, :timer)
```

### Event-Driven Command Hooks
Users can register automated commands (`:enter`, `:exit`, `:return`, `:receive`, `:focus`) with `add|del|list|clear`. When the corresponding event fires (e.g. user enters the room, or sends a gift), the registered command string (e.g. `:say 欢迎！` or `:play 晴天`) is queued into `MessageQueue`.

### Dual-Layer User Memory
- **Short-Term Memory**: Recent conversation turns stored in SQLite (`user_memories`).
- **Long-Term Memory**: Structured JSON containing **Immutable Directives** (hard rules, honorifics) and an **Evolving Profile** (interests, music tastes).
- **Consolidation**: Runs asynchronously in the background on room lifecycle and presence events without blocking active chat resolution.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `level` | 0 | `[<user>] [<level>]` | View own level, view target user's level, or set user level (0-9, requires operator privileges) |
| `admin` | 9 | `1/0 [<user>]` | Grant (1) or revoke (0) admin role in room UI; defaults to caller if user omitted |
| `alias` | 9 | `"<alias>" "<canonical>"` | Bind an alias username to a canonical user record |
| `say` | 1 | `<message>` | Post a message to room chat |
| `keyword` | 1 | `add/del/list/public/private <trigger> [resp]` | Manage keyword auto-reply rules (public or user-private scope) |
| `enter` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal automated command to run when entering the room |
| `exit` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal automated command to run when exiting the room |
| `return` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal automated command to run when returning to the room |
| `receive` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal automated command to run when receiving gifts/heat |
| `focus` | 1 | `[add\|del\|list\|clear] [cmd]` | Register personal automated command to run on study room focus count updates |
| `gift` | 5 | `[<user>]` | Send a gift to a user (falls back to yellow duck); defaults to caller if omitted |

`<user>` 参数既可以写分身名也可以写主账号名：DB 侧归属一律解析到 canonical，面向 Soul UI 的操作（在线列表、资料页、座位）自动解析成房间里当前可见的昵称。

## Data Model

| Model | Table | Key Fields |
|---|---|---|
| `User` | `users` | `username`, `level`, `canonical_user_id`, `created_at` |
| `Keyword` | `keywords` | `trigger`, `response`, `user_id` |
| `EnterEvent` | `enter_events` | `username`, `command` |
| `ExitEvent` | `exit_events` | `username`, `command` |
| `ReturnEvent` | `return_events` | `username`, `command` |
| `ReceiveEvent` | `receive_events` | `username`, `command` |
| `FocusEvent` | `focus_events` | `username`, `command` |
| `UserMemory` | `user_memories` | `username`, `memory_data`, `last_consolidated_at` |

## Extension Points

- **Role Policy additions**: Extend `RolePolicy` in `src/ushareiplay/core/roles.py` to support new operator sources or custom permission checks.
- **New event hook**: Create model + DAO under `src/ushareiplay/models/` and `src/ushareiplay/dal/`, add command in `src/ushareiplay/commands/`, register in `DatabaseManager`.
- **Memory schema changes**: Update `MemoryManager` structured schema validation and prompt builder.
