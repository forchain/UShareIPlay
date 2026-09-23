# Design Spec: Party Recommendation Management & Syncing

## Overview

This spec defines the design for party recommendation management in UShareIPlay. It introduces configuration, state management, active and passive recommendation status synchronization, the `:recommend` command, and `:info` status reporting.

---

## 1. Configuration & UI Locators

### 1.1 Config (`config.yaml`)
Add `create_party_recommendation` setting under `soul` and recommendation UI locators under `soul.elements`:

```yaml
soul:
  create_party_recommendation: true # 创建派对时默认开启推荐 (default: true)

  elements:
    party_recommendation_status: "cn.soulapp.android:id/tv_private_title" # 房间推荐状态 View
    party_recommendation_open: '//android.widget.TextView[@text="所有人"]' # 开放推荐选项
    party_recommendation_close: '//android.widget.TextView[@text="关闭推荐分发"]' # 关闭推荐选项
```

---

## 2. Room State & Info Integration

### 2.1 RoomState (`src/ushareiplay/state/room_state.py`)
Add `_recommendation_enabled: Optional[bool] = None` property to `RoomState`:
- `None`: Status uninitialized / not saved yet.
- `True`: Recommendation is open ("所有人").
- `False`: Recommendation is closed ("关闭推荐分发").

Expose getter and setter:
- `recommendation_enabled -> Optional[bool]`
- `clear()` resets `_recommendation_enabled` to `None`.

### 2.2 InfoManager (`src/ushareiplay/managers/info_manager.py`)
Delegate `recommendation_enabled` getter/setter to `RoomState`.

### 2.3 InfoCommand (`src/ushareiplay/commands/info.py`) & Template
In `InfoCommand.do_process()`:
- `party_recommendation`: `"开放"` if `recommendation_enabled is True`, `"关闭"` if `False`, `"未知"` if `None`.

In `config.yaml`:
- Update `info.response_template`:
```yaml
response_template: "播放模式: {play_mode}\n{current_playlist}\n{online_users}\n{party_duration}\n派对推荐: {party_recommendation}\n{song} - {singer} • {album} • {release_date}"
```

---

## 3. Party Recommendation Manager (`src/ushareiplay/managers/recommendation_manager.py`)

Create `RecommendationManager(Singleton)` to encapsulate UI detection and recommendation state updates:

### 3.1 UI Interaction Flow
- `inspect_current_ui_status() -> Optional[bool]`:
  - When the room title dialog (`chat_room_title`) is open, locate `party_recommendation_status` (`tv_private_title`).
  - Return `True` if text is `"所有人"`, `False` if text is `"关闭推荐分发"`, `None` if element not found.

- `update_recommendation_ui(target_state: bool) -> dict`:
  - With room title dialog open:
  - If current UI status does not match `target_state`:
    - Click `party_recommendation_status` (`tv_private_title`).
    - Click `party_recommendation_open` if `target_state` is True, or `party_recommendation_close` if False.
  - Update `RoomState.recommendation_enabled = target_state`.
  - Return `{'success': True, 'recommendation_enabled': target_state}`.

### 3.2 Active & Passive Synchronization Policy
1. **Active Sync (`ensure_synced_on_return()`)**:
   - Triggered when returning to / restoring room or after party creation.
   - If `RoomState.recommendation_enabled is None` (uninitialized/unsaved):
     - Click `chat_room_title` to open dialog.
     - Inspect UI status via `inspect_current_ui_status()`.
     - Target state = `config.get('soul', {}).get('create_party_recommendation', True)`.
     - If UI status differs from target state, execute `update_recommendation_ui(target_state)`.
     - Update `RoomState.recommendation_enabled`.
     - Press back to close title dialog.
   - If `RoomState.recommendation_enabled is not None`:
     - Skip opening title dialog.

2. **Passive Discrepancy Sync (`sync_ui_status_if_dialog_open()`)**:
   - Triggered whenever the room title dialog is opened for ANY reason (e.g. `RoomNameManager._update_title_ui` or manually clicking title).
   - Inspects UI status via `inspect_current_ui_status()`.
   - If UI status is found and differs from `RoomState.recommendation_enabled`, update `RoomState.recommendation_enabled` to match the actual UI status and log the discrepancy correction.

3. **Party Creation Flow (`PartyManager._create_party_flow`)**:
   - Check `soul.create_party_recommendation` (default `True`).
   - If `create_party_recommendation` is `False`, click `close_party_notification` (`party_recommendation_close`) during creation flow, and set `RoomState.recommendation_enabled = False`.
   - If `create_party_recommendation` is `True`, keep recommendation enabled (do not click close), and set `RoomState.recommendation_enabled = True`.

---

## 4. Recommend Command (`src/ushareiplay/commands/recommend.py`)

- **Prefix**: `recommend`
- **Level**: 1 (or admin level based on config)
- **Syntax**:
  - `:recommend` -> Toggles status (if currently `True` -> set to `False`, else set to `True`).
  - `:recommend on` / `:recommend 开启` -> Sets status to `True`.
  - `:recommend off` / `:recommend 关闭` -> Sets status to `False`.
- **Execution**:
  - Switch to Soul app.
  - Open title dialog (`chat_room_title`).
  - Execute `RecommendationManager.update_recommendation_ui(target_state)`.
  - Press back to return to room.
  - Return response template: `"派对推荐已设置为: {status}"` (where `status` is `"开放"` or `"关闭"`).

Add `recommend` entry to `config.yaml` commands list:
```yaml
  - prefix: "recommend"
    level: 1
    response_template: "派对推荐已设置为: {status}"
    error_template: "设置派对推荐失败: {error}"
```

---

## 5. Testing & Verification

1. Unit tests for `RoomState` recommendation state getter/setter and `clear()`.
2. Unit tests for `RecommendationManager` active/passive sync logic & state matching.
3. Unit tests for `InfoCommand` and `RecommendCommand` parameter parsing and response formatting.
4. Pytest suite execution (`uv run pytest -q`).
