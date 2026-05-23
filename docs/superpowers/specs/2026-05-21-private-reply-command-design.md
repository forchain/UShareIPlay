# Design Spec: Private Reply Command Prefix

**Date:** 2026-05-21
**Status:** Draft
**Topic:** Route command output to private chat with `$` prefix

## 1. Problem Description
Soul public chat risk controls are strict enough that normal command results can fail to send or contribute to account risk even when the content is not sensitive. Existing command replies go to the public room by default, which creates avoidable public-message volume and makes command results less reliable.

The system needs a way for a user to request command results privately while keeping the command execution path efficient and avoiding unnecessary public fallback messages.

## 2. Proposed Solution
Add `$` as a command prefix modifier that routes command output to the triggering user through Soul private chat.

`$` is not a new command namespace. `$play song` should execute the existing `play` command and mark that command invocation as requiring private replies.

### 2.1. Public Confirmation Behavior
- The default command confirmation message remains public for efficiency and operational visibility.
- Only command execution output is private in `$` mode.
- Command output includes success responses, error responses, parameter validation messages, and help-style command responses that would otherwise be sent to the public room.

### 2.2. Private Reply Behavior
For each private output message:

1. Open the online user list.
2. Open the triggering user's info page using the existing online-user lookup flow.
3. Click the user avatar: `cn.soulapp.android:id/ivAvatar`.
4. Click the private chat button: `cn.soulapp.android:id/tv_chat_secret`.
5. Click the message input: `cn.soulapp.android:id/et_sendmessage`.
6. Enter the output message.
7. Click send: `cn.soulapp.android:id/btn_send`.
8. Return to the chat room by clicking either:
   - `cn.soulapp.android:id/lottie_in_party`
   - existing `floating_entry`

The system should attempt this full lookup and navigation sequence for each private output message. If the user leaves between multiple outputs, the first failed private send stops any later private sends for that command flow.

### 2.3. Failure Behavior
- If the system cannot enter private chat before sending the first private output, it should stop silently.
- It must not send a public error fallback for private-reply setup failures.
- Failures should be logged for troubleshooting.
- If one private output fails, later outputs in the same command flow should not continue.

This follows the product principle for this change: if a message is not necessary for public chat, do not send it publicly.

### 2.4. Prefix Semantics
- Existing public prefixes remain unchanged: `:` and `：`.
- Existing silent slash prefixes remain unchanged: `/` and `／`.
- `$` marks the invocation as private reply mode and strips the `$` before normal command parsing.
- The first version supports `$command` only. Combined forms such as `$/command` are intentionally out of scope to keep command routing predictable.

## 3. Implementation Details

### 3.1. Data Model
Extend `MessageInfo` with a private-reply flag, for example:

```python
private_reply: bool = False
```

This keeps routing metadata attached to the message without changing command modules.

### 3.2. Command Parsing and Dispatch
Update command ingestion and dispatch so messages beginning with `$` are accepted as command candidates.

Expected flow:

1. Detect `$` at message ingestion or command-manager normalization.
2. Set `MessageInfo.private_reply = True`.
3. Strip `$`.
4. Continue parsing the remaining content through the existing command parser.
5. Send the normal public confirmation message.
6. Route command result output through the private sender instead of `handler.send_message`.

### 3.3. Private Sender
Add a focused manager/helper for private chat output. It should use existing Soul UI helper methods and existing `UserManager.open_user_profile_from_online_list()` for user lookup.

The helper should return a boolean success indicator. `False` means no more private outputs should be attempted for that command flow.

### 3.4. UI Selectors
The private sender needs selectors for:

- Avatar: `cn.soulapp.android:id/ivAvatar`
- Private chat button: `cn.soulapp.android:id/tv_chat_secret`
- Message input: `cn.soulapp.android:id/et_sendmessage`
- Send button: `cn.soulapp.android:id/btn_send`
- In-party return button: `cn.soulapp.android:id/lottie_in_party`
- Existing floating return entry: `floating_entry`

Selectors should be configured consistently with the existing `config.yaml` selector structure when possible.

## 4. Testing Strategy

### 4.1. Unit Tests
Add focused tests around command routing:

- `$play song` is recognized as a valid command invocation.
- `$play song` parses and dispatches as `play` with `private_reply=True`.
- Public confirmation is still sent for `$` commands.
- Command result output uses the private sender instead of public `send_message`.
- Command errors use the private sender instead of public `send_message`.
- If the private sender returns `False`, later private outputs are not attempted.
- Existing `:`, `：`, `/`, and `／` behavior remains unchanged.

### 4.2. UI Helper Tests
Use mocks around the handler and user manager to verify the private sender sequence:

- Opens target user from the online list.
- Clicks avatar.
- Opens private chat.
- Sends text through the private input and send button.
- Returns to the room using `lottie_in_party` when available.
- Falls back to `floating_entry` when `lottie_in_party` is unavailable.
- Returns `False` without public fallback when any required step fails.

### 4.3. Manual/E2E Validation
Real-device validation is required because this feature depends on Soul UI navigation:

- Trigger a `$` command from an online user and verify the public room only shows the confirmation.
- Verify the command result appears in private chat.
- Trigger a command that returns an error and verify the error appears in private chat.
- Have the user leave before output sends and verify no public fallback is posted.

## 5. Out of Scope
- Supporting combined prefix forms such as `$/play`.
- Making all command progress messages private if they bypass `CommandManager` and call `handler.send_message` directly from inside a command.
- Retrying private sends after user lookup fails.
- Publicly notifying other users that private delivery failed.

## 6. Design Review Notes
- **Architecture:** Keep the behavior in command routing and a private sender helper so existing command modules remain mostly unchanged.
- **Risk Control:** Public chat volume is minimized. Failure paths avoid public fallback messages.
- **Reliability:** Each private send revalidates online presence through the online user list, so later outputs stop when the user leaves.
- **Observability:** Failures are logged instead of posted publicly.
