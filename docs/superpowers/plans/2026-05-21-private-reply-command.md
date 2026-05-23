# Private Reply Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `$` command prefix support so command execution output is delivered via Soul private chat to the triggering user, while default command confirmation stays in public chat.

**Architecture:** Extend command message metadata with a private-reply flag, detect and normalize `$` in command parsing flow, and route command output through a dedicated private sender helper. Keep existing command modules unchanged and enforce silent-stop behavior when private delivery setup/send fails.

**Tech Stack:** Python, Appium/Selenium wrappers in existing handlers, `pytest`, `unittest.mock`.

---

### Task 1: Add Private-Reply Metadata and Prefix Normalization

**Files:**
- Modify: `src/ushareiplay/models/message_info.py`
- Modify: `src/ushareiplay/managers/command_manager.py`
- Modify: `src/ushareiplay/managers/message_manager.py`
- Test: `tests/test_command_manager_runtime_context.py`

- [ ] **Step 1: Write failing tests for `$` normalization and routing metadata**

```python
def test_normalize_command_candidate_private_prefix():
    manager = CommandManager.instance()
    private_reply, normalized = manager._extract_private_reply_and_normalize("  $play abc")
    assert private_reply is True
    assert normalized == "play abc"

def test_normalize_command_candidate_regular_prefix():
    manager = CommandManager.instance()
    private_reply, normalized = manager._extract_private_reply_and_normalize(" :help")
    assert private_reply is False
    assert normalized == "help"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest -q tests/test_command_manager_runtime_context.py -k private_prefix`
Expected: FAIL because `_extract_private_reply_and_normalize` does not exist.

- [ ] **Step 3: Implement metadata and normalization**

```python
@dataclass
class MessageInfo:
    content: str
    nickname: str
    silent: bool = False
    private_reply: bool = False
```

```python
def _extract_private_reply_and_normalize(self, raw: str) -> tuple[bool, str]:
    s = (raw or "").lstrip()
    private_reply = bool(s) and s[0] == "$"
    if private_reply:
        s = s[1:].lstrip()
    if s and s[0] in COMMAND_PREFIXES:
        s = s[1:]
    return private_reply, s.lstrip()
```

- [ ] **Step 4: Wire parser flow to preserve `private_reply` on each invocation**

Use `_extract_private_reply_and_normalize` in `handle_message_commands` and combine with existing `message_info.private_reply` if already set upstream.

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q tests/test_command_manager_runtime_context.py`
Expected: PASS for new private-prefix tests and no regression in existing tests.

- [ ] **Step 6: Commit**

```bash
git add src/ushareiplay/models/message_info.py src/ushareiplay/managers/command_manager.py src/ushareiplay/managers/message_manager.py tests/test_command_manager_runtime_context.py
git commit -m "feat: add private-reply command metadata and prefix normalization"
```

---

### Task 2: Implement Private Message Sender for Soul UI Flow

**Files:**
- Modify: `src/ushareiplay/managers/user_manager.py`
- Test: `tests/test_private_reply_sender.py`

- [ ] **Step 1: Write failing tests for private send sequence**

```python
def test_send_private_message_success_uses_avatar_chat_input_send_and_return(...):
    ...

def test_send_private_message_fallback_to_floating_entry_when_lottie_missing(...):
    ...

def test_send_private_message_failure_returns_false_without_raise(...):
    ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest -q tests/test_private_reply_sender.py`
Expected: FAIL because `send_private_message_to_user` is not implemented.

- [ ] **Step 3: Implement private sender in `UserManager`**

Add `send_private_message_to_user(nickname: str, message: str) -> bool`:
- Reuse `open_user_profile_from_online_list`.
- Click `cn.soulapp.android:id/ivAvatar`.
- Click `cn.soulapp.android:id/tv_chat_secret`.
- Input at `cn.soulapp.android:id/et_sendmessage`.
- Click `cn.soulapp.android:id/btn_send`.
- Return by clicking `cn.soulapp.android:id/lottie_in_party` or `floating_entry`.
- Return `False` on any failure, log details, never throw.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_private_reply_sender.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/managers/user_manager.py tests/test_private_reply_sender.py
git commit -m "feat: add Soul private message sender with room-return fallback"
```

---

### Task 3: Route `$` Command Outputs to Private Sender

**Files:**
- Modify: `src/ushareiplay/managers/command_manager.py`
- Test: `tests/test_command_manager_runtime_context.py`

- [ ] **Step 1: Write failing tests for output routing**

```python
@pytest.mark.asyncio
async def test_private_reply_keeps_public_confirmation_and_private_result(...):
    # confirmation -> handler.send_message called
    # result -> user_manager.send_private_message_to_user called
    ...

@pytest.mark.asyncio
async def test_private_reply_routes_error_output_to_private(...):
    ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest -q tests/test_command_manager_runtime_context.py -k private_reply`
Expected: FAIL because output routing still uses only public sender.

- [ ] **Step 3: Implement routing helpers in `CommandManager`**

Add focused helpers:
- `_send_confirmation_message(...)` always public (respect existing silent command behavior).
- `_send_command_output(...)` routes to private sender if `private_reply=True`; otherwise public.
- When private sender returns `False`, stop additional output attempts for current command flow.

- [ ] **Step 4: Keep compatibility with silent slash commands**

Ensure `/` behavior remains unchanged and does not regress; only `$` changes output channel.

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q tests/test_command_manager_runtime_context.py tests/test_command_manager_silent_commands.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ushareiplay/managers/command_manager.py tests/test_command_manager_runtime_context.py
git commit -m "feat: route dollar-prefixed command output to private chat"
```

---

### Task 4: Ensure Missed/Realtime Message Parsing Accepts `$`

**Files:**
- Modify: `src/ushareiplay/managers/message_manager.py`
- Test: `tests/test_runtime_queue_pipeline.py`

- [ ] **Step 1: Write failing tests for `$` messages entering command pipeline**

```python
@pytest.mark.asyncio
async def test_process_new_messages_accepts_dollar_prefix(...):
    ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest -q tests/test_runtime_queue_pipeline.py -k dollar`
Expected: FAIL because regex only accepts `[:：/／]`.

- [ ] **Step 3: Expand prefix parsing to include `$`**

Update regex/prefix handling in `process_new_messages` and `process_missed_messages` so `$` commands are accepted and preserve content for downstream normalization.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q tests/test_runtime_queue_pipeline.py tests/test_message_manager*.py`
Expected: PASS (or run the closest existing message-manager test module names in repo).

- [ ] **Step 5: Commit**

```bash
git add src/ushareiplay/managers/message_manager.py tests/test_runtime_queue_pipeline.py
git commit -m "feat: accept dollar-prefixed commands in message ingestion"
```

---

### Task 5: Regression Verification and Documentation Sync

**Files:**
- Modify: `docs/users.md` (only if command prefix behavior is documented there)
- Modify: `README.md` (only if command prefix behavior is documented there)

- [ ] **Step 1: Run focused regression suite**

Run:
- `uv run pytest -q tests/test_command_manager_runtime_context.py`
- `uv run pytest -q tests/test_command_manager_silent_commands.py`
- `uv run pytest -q tests/test_runtime_queue_pipeline.py`
- `uv run pytest -q tests/test_private_reply_sender.py`

Expected: PASS.

- [ ] **Step 2: Run broader command pipeline sanity**

Run: `uv run pytest -q tests/test_command_manager_*.py tests/test_simple_command_modules_class_only.py tests/test_stateful_command_modules_class_only.py`
Expected: PASS.

- [ ] **Step 3: Update docs if needed**

Document `$` prefix semantics:
- Public confirmation remains public.
- Execution outputs are private.
- Private setup/send failure is silent (no public fallback).

- [ ] **Step 4: Final commit**

```bash
git add docs/users.md README.md
git commit -m "docs: document dollar-prefix private reply behavior"
```

Only include files actually changed.

---

## Notes for Implementers
- Keep changes scoped to routing and sender helper; avoid refactoring unrelated command architecture.
- Preserve existing logging style and resilience patterns.
- Do not introduce public fallback output on private-send failures.
- Ensure selector usage is centralized and consistent with existing handler conventions.
