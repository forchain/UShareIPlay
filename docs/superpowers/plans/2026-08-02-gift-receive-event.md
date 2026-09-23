# Gift Receive Event Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect gift receive and heat contribution messages from Soul App chat, trigger `ChatIntakeKind.GIFT_RECEIVE` events, log them, and execute user-configured commands stored in database via `:receive`.

**Architecture:** Extend `ChatIntake` classification with gift regex patterns and room owner matching. Create a `ReceiveEvent` Tortoise ORM model and `ReceiveDao` for SQLite storage, a `:receive` command module for managing user rules, and hook the classification into `MessageContentEvent` and `CommandManager`.

**Tech Stack:** Python 3.10+, Tortoise ORM, SQLite, pytest, shlex, re.

## Global Constraints

- **Python & pytest:** Run tests with `uv run pytest -q`.
- **Imports:** Preserve relative or package imports under `ushareiplay`.
- **Command prefix:** Command prefix is `:receive` supporting `add`, `del`, `list`, `clear`.
- **Owner matching:** Type 1 gift messages (`souler[<giver>]送给<receiver>`) only trigger if `<receiver>` equals `soul.room_owner` in config.

---

### Task 1: Chat Intake Gift Classification

**Files:**
- Modify: `src/ushareiplay/core/chat_intake.py`
- Test: `tests/test_chat_intake.py`

**Interfaces:**
- Consumes: `classify_chat_line(raw: str, room_owner: str | None = None)`
- Produces: `ChatIntakeKind.GIFT_RECEIVE`

- [ ] **Step 1: Write failing tests in `tests/test_chat_intake.py`**

```python
def test_gift_type1_matches_when_receiver_is_room_owner():
    result = classify_chat_line("souler[🍻🥂🥃🍸🍷🍺]送给Joyer", room_owner="Joyer")
    assert result.kind == ChatIntakeKind.GIFT_RECEIVE
    assert result.nickname == "🍻🥂🥃🍸🍷🍺"
    assert result.text == "🍻🥂🥃🍸🍷🍺"

def test_gift_type1_ignored_when_receiver_is_not_room_owner():
    result = classify_chat_line("souler[Alice]送给Bob", room_owner="Joyer")
    assert result.kind == ChatIntakeKind.PLAIN_CHAT

def test_gift_type2_heat_contribution_matches():
    result = classify_chat_line("08-02 17:44:58 [I] 恭喜🍻🥂🥃🍸🍷🍺在此房间贡献出3120热力值")
    assert result.kind == ChatIntakeKind.GIFT_RECEIVE
    assert result.nickname == "🍻🥂🥃🍸🍷🍺"
    assert result.text == "🍻🥂🥃🍸🍷🍺"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_chat_intake.py`
Expected: FAIL due to missing `GIFT_RECEIVE` attribute or regex matching.

- [ ] **Step 3: Implement gift classification in `src/ushareiplay/core/chat_intake.py`**

Add `GIFT_RECEIVE = "gift_receive"` to `ChatIntakeKind`.
Add patterns:
```python
_GIFT_TYPE1_PATTERN = re.compile(r"souler\[(.+?)\]送给([^\s【]+)")
_GIFT_TYPE2_PATTERN = re.compile(r"恭喜(.+?)在此房间贡献出\d+热力值")
```
In `classify_chat_line(raw: str, room_owner: str | None = None)`:
Check Type 1 gift match and compare `receiver.strip() == room_owner.strip()` if `room_owner` is provided.
Check Type 2 gift match.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_chat_intake.py`
Expected: PASS

- [ ] **Step 5: Commit Task 1**

```bash
git add src/ushareiplay/core/chat_intake.py tests/test_chat_intake.py
git commit -m "feat: add GIFT_RECEIVE chat intake classification for gift and heat messages"
```

---

### Task 2: ReceiveEvent Model and ReceiveDao Data Access Layer

**Files:**
- Create: `src/ushareiplay/models/receive_event.py`
- Modify: `src/ushareiplay/models/__init__.py`
- Create: `src/ushareiplay/dal/receive_dao.py`
- Test: `tests/test_receive_dao.py`

**Interfaces:**
- Produces: `ReceiveEvent` Tortoise ORM model and `ReceiveDao` (`create`, `get_by_username`, `delete_by_id`, `delete_all_by_username`)

- [ ] **Step 1: Write failing test in `tests/test_receive_dao.py`**

```python
import pytest
from ushareiplay.dal.receive_dao import ReceiveDao

@pytest.mark.asyncio
async def test_receive_dao_crud(db_init):
    event = await ReceiveDao.create("Alice", ":play song")
    assert event.id is not None
    assert event.command == ":play song"

    items = await ReceiveDao.get_by_username("Alice")
    assert len(items) == 1
    assert items[0].command == ":play song"

    deleted = await ReceiveDao.delete_by_id(event.id)
    assert deleted is True

    items = await ReceiveDao.get_by_username("Alice")
    assert len(items) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_receive_dao.py`
Expected: FAIL (ModuleNotFoundError: `ushareiplay.dal.receive_dao`)

- [ ] **Step 3: Create `ReceiveEvent` and `ReceiveDao`**

Create `src/ushareiplay/models/receive_event.py`:
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

Create `src/ushareiplay/dal/receive_dao.py`:
```python
from typing import Optional, List
from ushareiplay.models.receive_event import ReceiveEvent
from ushareiplay.dal.user_dao import UserDAO

class ReceiveDao:
    @staticmethod
    async def create(username: str, command: str) -> ReceiveEvent:
        user = await UserDAO.get_or_create(username=username)
        return await ReceiveEvent.create(user=user, command=command)

    @staticmethod
    async def get_by_username(username: str) -> List[ReceiveEvent]:
        effective_user = await UserDAO.get_or_create(username=username)
        return await ReceiveEvent.filter(user__id=effective_user.id).order_by('id').prefetch_related('user')

    @staticmethod
    async def get_by_id(command_id: int) -> Optional[ReceiveEvent]:
        return await ReceiveEvent.get_or_none(id=command_id).prefetch_related('user')

    @staticmethod
    async def delete_by_id(command_id: int) -> bool:
        command = await ReceiveEvent.get_or_none(id=command_id)
        if command:
            await command.delete()
            return True
        return False

    @staticmethod
    async def delete_all_by_username(username: str) -> int:
        effective_user = await UserDAO.get_or_create(username=username)
        return await ReceiveEvent.filter(user__id=effective_user.id).delete()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_receive_dao.py`
Expected: PASS

- [ ] **Step 5: Commit Task 2**

```bash
git add src/ushareiplay/models/receive_event.py src/ushareiplay/models/__init__.py src/ushareiplay/dal/receive_dao.py tests/test_receive_dao.py
git commit -m "feat: add ReceiveEvent model and ReceiveDao"
```

---

### Task 3: Receive Command & CommandManager Event Dispatch

**Files:**
- Create: `src/ushareiplay/commands/receive.py`
- Modify: `src/ushareiplay/managers/command_manager.py`
- Test: `tests/test_receive_command.py`

**Interfaces:**
- Consumes: `ReceiveDao`
- Produces: `ReceiveCommand` (prefix `:receive`), `CommandManager.notify_gift_receive(username)`

- [ ] **Step 1: Write failing test in `tests/test_receive_command.py`**

```python
import pytest
from ushareiplay.commands.receive import ReceiveCommand
from ushareiplay.models.message_info import MessageInfo

@pytest.mark.asyncio
async def test_receive_command_add_and_trigger(db_init):
    cmd = ReceiveCommand()
    msg_info = MessageInfo(content=":receive add \":say Thanks for the gift!\"", nickname="Alice")
    result = await cmd.do_process(msg_info, ["add", ":say Thanks for the gift!"])
    assert "message" in result
    assert "已添加" in result["message"]

    # Trigger gift receive callback
    await cmd.user_gift_receive("Alice")
    # MessageQueue should have queued message
    from ushareiplay.core.message_queue import MessageQueue
    queue_msg = await MessageQueue.instance().get_message()
    assert queue_msg.nickname == "Alice"
    assert queue_msg.content == ":say Thanks for the gift!"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_receive_command.py`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implement `ReceiveCommand` and `notify_gift_receive`**

Create `src/ushareiplay/commands/receive.py`:
```python
import traceback
import shlex
from ushareiplay.core.base_command import BaseCommand
from ushareiplay.dal.receive_dao import ReceiveDao

class ReceiveCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理收礼物命令时出错'

    async def do_process(self, message_info, parameters):
        try:
            original_content = message_info.content
            parts = original_content.split(None, 1)
            if len(parts) < 2:
                return {'error': '缺少参数。使用: :receive [add|del|list|clear]'}
            params = shlex.split(parts[1])
        except ValueError:
            return {'error': '参数格式错误，带空格的参数请使用引号包裹'}

        if not params:
            return {'error': '缺少参数。使用: :receive [add|del|list|clear]'}

        operation = params[0]
        username = message_info.nickname

        if operation == 'add':
            if len(params) < 2:
                return {'error': '缺少命令内容。使用: :receive add "命令内容"'}
            command = params[1]
            if not command.startswith((':', '：', '/', '／')):
                return {'error': '命令必须以命令前缀(:/：或//／)开头，例如 ":say 谢谢"' }
            await ReceiveDao.create(username, command)
            return {'message': f'已添加收礼物命令: {command}'}

        elif operation == 'del':
            if len(params) < 2:
                return {'error': '缺少命令ID。使用: :receive del <id>'}
            try:
                command_id = int(params[1])
            except ValueError:
                return {'error': '命令ID必须是数字'}
            deleted = await ReceiveDao.delete_by_id(command_id)
            if deleted:
                return {'message': f'已删除命令 ID: {command_id}'}
            return {'error': f'未找到命令 ID: {command_id}'}

        elif operation == 'list':
            commands = await ReceiveDao.get_by_username(username)
            if not commands:
                return {'message': '您还没有设置任何收礼物命令'}
            message_lines = ['您的收礼物命令列表:']
            for c in commands:
                message_lines.append(f'  [{c.id}] {c.command}')
            return {'message': '\n'.join(message_lines)}

        elif operation == 'clear':
            count = await ReceiveDao.delete_all_by_username(username)
            if count > 0:
                return {'message': f'已清除 {count} 个收礼物命令'}
            return {'message': '您没有任何收礼物命令需要清除'}

        return {'error': f'未知操作: {operation}。使用: :receive [add|del|list|clear]'}

    async def user_gift_receive(self, username: str):
        try:
            commands = await ReceiveDao.get_by_username(username)
            if not commands:
                return
            from ushareiplay.core.message_queue import MessageQueue
            from ushareiplay.models.message_info import MessageInfo

            message_queue = MessageQueue.instance()
            for cmd in commands:
                message_info = MessageInfo(content=cmd.command, nickname=username)
                await message_queue.put_message(message_info)
        except Exception:
            self.handler.log_error(f"Error in receive user_gift_receive: {traceback.format_exc()}")
```

In `src/ushareiplay/managers/command_manager.py`:
Add method `notify_gift_receive`:
```python
    async def notify_gift_receive(self, username: str):
        for module in self.get_command_modules().values():
            try:
                if hasattr(module.command, 'user_gift_receive'):
                    await module.command.user_gift_receive(username)
            except Exception:
                self.logger.error(f"Error in command user_gift_receive: {traceback.format_exc()}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest -q tests/test_receive_command.py`
Expected: PASS

- [ ] **Step 5: Commit Task 3**

```bash
git add src/ushareiplay/commands/receive.py src/ushareiplay/managers/command_manager.py tests/test_receive_command.py
git commit -m "feat: add ReceiveCommand and CommandManager notify_gift_receive"
```

---

### Task 4: Message Content Integration & Config Support

**Files:**
- Modify: `src/ushareiplay/events/message_content.py`
- Test: `tests/test_message_content_gift.py`

**Interfaces:**
- Consumes: `classify_chat_line`, `CommandManager.notify_gift_receive`

- [ ] **Step 1: Write failing test in `tests/test_message_content_gift.py`**

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from ushareiplay.events.message_content import MessageContentEvent
from ushareiplay.core.chat_intake import ChatIntakeKind, classify_chat_line

def test_classify_gift_with_room_owner_config():
    raw = "souler[Bob]送给Joyer"
    res = classify_chat_line(raw, room_owner="Joyer")
    assert res.kind == ChatIntakeKind.GIFT_RECEIVE
    assert res.nickname == "Bob"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_message_content_gift.py`
Expected: FAIL

- [ ] **Step 3: Modify `MessageContentEvent.handle`**

In `MessageContentEvent.handle`:
Retrieve `room_owner` from handler config:
```python
room_owner = None
if hasattr(self.handler, 'config') and isinstance(self.handler.config, dict):
    soul_cfg = self.handler.config.get("soul", {})
    if isinstance(soul_cfg, dict):
        room_owner = soul_cfg.get("room_owner")
    if not room_owner:
        room_owner = self.handler.config.get("room_owner")
```
Pass `room_owner` into `classify_chat_line(content, room_owner=room_owner)` calls.

When `result.kind == ChatIntakeKind.GIFT_RECEIVE`:
```python
chat_logger.critical(content)
self.logger.info(f"Gift received from: {result.nickname}")
await self._notify_gift_receive(result.nickname)
```
Add method `_notify_gift_receive(username)`:
```python
async def _notify_gift_receive(self, username: str):
    try:
        command_manager = CommandManager.instance()
        await command_manager.notify_gift_receive(username)
    except Exception as e:
        self.logger.error(f"Error notifying gift receive: {str(e)}")
```

- [ ] **Step 4: Run full test suite to verify everything passes**

Run: `uv run pytest -q`
Expected: ALL PASS

- [ ] **Step 5: Commit Task 4**

```bash
git add src/ushareiplay/events/message_content.py tests/test_message_content_gift.py
git commit -m "feat: integrate gift receive detection into MessageContentEvent"
```
