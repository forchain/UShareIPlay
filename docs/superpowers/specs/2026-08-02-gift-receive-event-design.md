# Design Spec: Gift Receive Event Detection & Command Dispatch

## Overview

This spec defines the gift receive event system for UShareIPlay. When specific gift/heat contribution messages are detected in the Soul App chat stream, the system triggers a **Gift Receive Event** (`ChatIntakeKind.GIFT_RECEIVE`), logs the occurrence, and executes user-configured actions stored in the SQLite database via the `:receive` command.

## Target Gift Message Formats

1. **Type 1 (Gift Sent to Room Owner)**:
   - Format: `souler[<giver>]送给<receiver>` (e.g. `souler[🍻🥂🥃🍸🍷🍺]送给Joyer` followed by `【为你爆灯】`)
   - Condition: `<receiver>` must match the configured `room_owner` in `config.yaml`.
2. **Type 2 (Heat Contribution)**:
   - Format: `恭喜<giver>在此房间贡献出<heat_value>热力值` (e.g. `恭喜🍻🥂🥃🍸🍷🍺在此房间贡献出3120热力值`)
   - Condition: Always triggers for any giver contributing heat value in the room.

---

## 1. Configuration & Intake Classification

### 1.1 Config (`config.yaml`)
Add room owner setting under `soul`:
```yaml
soul:
  room_owner: "Joyer"
```

### 1.2 Chat Intake (`src/ushareiplay/core/chat_intake.py`)
- Add `GIFT_RECEIVE = "gift_receive"` to `ChatIntakeKind`.
- Define compiled regexes:
  - `_GIFT_TYPE1_PATTERN = re.compile(r"souler\[(.+?)\]送给([^\s【]+)")`
  - `_GIFT_TYPE2_PATTERN = re.compile(r"恭喜(.+?)在此房间贡献出\d+热力值")`
- Update `classify_chat_line(raw: str, room_owner: str | None = None) -> ChatIntakeResult`:
  - Matches Type 1 regex -> if `room_owner` matches `receiver.strip()`, return `ChatIntakeResult(kind=ChatIntakeKind.GIFT_RECEIVE, nickname=giver, text=giver, raw=raw)`.
  - Matches Type 2 regex -> return `ChatIntakeResult(kind=ChatIntakeKind.GIFT_RECEIVE, nickname=giver, text=giver, raw=raw)`.

---

## 2. Database Model & Data Access Layer

### 2.1 Tortoise ORM Model (`src/ushareiplay/models/receive_event.py`)
```python
from tortoise import fields
from tortoise.models import Model

class ReceiveEvent(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="receive_events")
    command = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True, null=True)

    class Meta:
        table = "receive_events"

    def __str__(self):
        return f"ReceiveEvent(id={self.id}, user={self.user_id}, command={self.command})"
```
Export `ReceiveEvent` in `src/ushareiplay/models/__init__.py`.

### 2.2 Data Access Object (`src/ushareiplay/dal/receive_dao.py`)
Provides async CRUD operations:
- `create(username: str, command: str) -> ReceiveEvent`
- `get_by_username(username: str) -> List[ReceiveEvent]`
- `get_by_id(command_id: int) -> Optional[ReceiveEvent]`
- `delete_by_id(command_id: int) -> bool`
- `delete_all_by_username(username: str) -> int`

---

## 3. Command & Dispatch Pipeline

### 3.1 Command (`src/ushareiplay/commands/receive.py`)
- Prefix: `:receive`
- Operations:
  - `:receive add "<command>"` — Add command rule for current user.
  - `:receive del <id>` — Delete command rule by ID.
  - `:receive list` — List command rules for current user.
  - `:receive clear` — Clear all command rules for current user.
- Callback method `user_gift_receive(self, username: str)`:
  - Fetches rules for `username` via `ReceiveDao.get_by_username(username)`.
  - Puts corresponding `MessageInfo` instances into `MessageQueue`.

### 3.2 Command Manager (`src/ushareiplay/managers/command_manager.py`)
Add `notify_gift_receive(username: str)` to invoke `user_gift_receive(username)` on registered command modules.

### 3.3 Event Handler (`src/ushareiplay/events/message_content.py`)
- Retrieves `room_owner` from `self.handler.config`.
- Passes `room_owner` to `classify_chat_line`.
- On `ChatIntakeKind.GIFT_RECEIVE`:
  - Logs line to `chat_logger.critical(...)`.
  - Invokes `CommandManager.instance().notify_gift_receive(result.nickname)`.

---

## 4. Testing & Verification

1. Unit tests for `classify_chat_line` with Type 1 & Type 2 gift messages (`tests/test_chat_intake.py`).
2. Unit tests for `ReceiveDao` and `ReceiveCommand` CRUD and queue dispatch (`tests/test_receive_command.py`).
3. Verification via `pytest`.
