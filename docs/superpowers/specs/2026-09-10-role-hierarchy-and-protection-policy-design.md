# Design Spec: Configurable Role Hierarchy, Console Unification, and Human vs Automation Protection Policies

**Issue:** [#288](https://github.com/forchain/UShareIPlay/issues/288)  
**Date:** 2026-09-10  
**Status:** Ready for Implementation  

## Problem Statement

Currently, administrator names (`{"Joyer", "Timer", "Outlier", "Chainer", "Console", "Agent"}`) are hardcoded in application logic. This causes multiple operational and architectural problems:

1. **Inflexible Role Configuration**: Any change to administrators or system users requires code changes rather than updating configuration files.
2. **Conflation of Human Operators and Automated Roles**: The system treats human administrators and automated system tasks identically under a single static set. In reality:
   - When a human room owner or administrator plays a playlist, they welcome attendees playing music and do not need their playlist locked down.
   - When an attendee asks an administrator to change music, the administrator is currently blocked by the attendee's playlist protection because the system does not allow administrators to override active user playlists.
   - During sleep protection windows, automated timers (such as hourly chimes or radio triggers) previously bypassed sleep checks and disturbed sleeping attendees, while human administrators manually testing or playing music were blocked by sleep mode.
3. **Disjointed Console Identity**: Console operations and Room Owner operations represent the same authoritative operator identity in this deployment, but are treated as distinct entities throughout the codebase.

## Solution

1. **Externalize and Categorize Roles in Configuration**:
   - Strictly classify actors into three explicit tiers in configuration:
     - **Room Owner (房主)**: e.g. `Joyer`
     - **Administrators (管理员)**: e.g. `Outlier`, `Chainer`
     - **System Roles (系统角色)**: e.g. `Timer`, `Agent`
   - Unify `Console` and Room Owner: any permission or ownership check treats `Console` as the Room Owner.
2. **Asymmetric Protection Policy for Human Operators (Room Owner / Admin / Console)**:
   - **Unprotected Playback**: When a room owner or administrator is playing a playlist, no playlist protection is enforced; any attendee is welcome to queue or start songs.
   - **Protection Override**: When an attendee is playing a playlist, room owners and administrators can override playlist protection upon manual request or operator discretion.
   - **Sleep Override**: Manual commands dispatched by room owners, console, or administrators are permitted during sleep protection windows.
3. **Strict Protection Enforcement for Automated Roles (Timer / Agent)**:
   - Automated triggers have no subjective human judgment. They must never interrupt an active user's protected playlist.
   - Automated triggers must never break sleep protection windows (e.g. automated periodic music cannot wake up attendees).
   - When a system role is playing background music, it does not lock the playlist; attendees or administrators can play music anytime.

## User Stories

1. As a room owner, I want administrator usernames configured in `config.yaml` rather than hardcoded in source code, so that I can update room administrators without code modification.
2. As a room owner, I want system roles (such as `Timer` and `Agent`) separated from human administrator accounts in configuration, so that the bot differentiates between autonomous automation and human actions.
3. As a room owner, I want `Console` to be recognized as the Room Owner, so that backend operator inputs carry the full authority and privileges of the room owner.
4. As an attendee, I want to be able to request a song even when an administrator or room owner is currently playing a playlist, so that the music experience remains open and participatory.
5. As an administrator playing a playlist, I do not want my playlist to lock out other room attendees, so that other attendees feel welcomed to share songs.
6. As an attendee who is actively playing a playlist and still in the room, I want my playlist protected against automated timer and agent actions, so that background automation does not cut off my music.
7. As an attendee who is actively playing a playlist, I want an administrator or room owner to be able to change songs or playlists if I ask them to, so that human operator assistance is not blocked by playlist protection.
8. As a room attendee during the sleep protection window (e.g. 23:00-06:00), I want automated timers and agents to be blocked from initiating loud music commands, so that my rest is not disturbed by automated schedules.
9. As a room owner or administrator, I want to be able to manually trigger music commands during the sleep protection window if necessary, so that human operator intervention is not blocked by automated sleep guards.
10. As a room attendee, I want my own playlist to remain protected against other normal attendees while I or my avatars remain in the room, so that my queue is not interrupted by unauthorized guests.
11. As an attendee, I want to be able to switch my own playlist using my primary name or registered avatar without being blocked by self-protection.
12. As a system timer, when no attendee is playing and sleep window is not active, I want to be able to play scheduled background music smoothly.
13. As a room owner, I want case-insensitive username matching for administrators and system roles, so that slight capitalization discrepancies do not cause permission failures.
14. As a system operator, I want backward-compatible configuration fallbacks if legacy configuration keys are present, so that existing deployments continue to run safely.

## Implementation Decisions

- **Role Taxonomy and Unification Contract**:
  - Roles are defined via configuration: `room_owner` (string, default `"Joyer"`), `admin_users` (list of strings, default `["Outlier", "Chainer"]`), and `system_users` (list of strings, default `["Timer", "Agent"]`).
  - The static `SYSTEM_AND_ADMIN_USERS` set in `InfoManager` is removed.
  - No separate "Console" role exists. Backend and console operations (CLI inputs, post-party automations, agent spool commands) execute directly under the identity of the configured `room_owner`.
  - A unified role query interface evaluates actor identity:
    - `is_room_owner(user)`: Returns true if `user` matches configured `room_owner` (case-insensitive).
    - `is_admin(user)`: Returns true if `is_room_owner(user)` is true or `user` is in `admin_users`.
    - `is_system_user(user)`: Returns true if `user` is in `system_users`.
    - `is_human_operator(user)`: Returns true if `is_admin(user)` is true (Room Owner or Admins).
- **Playlist Protection Behavior Matrix**:
  - In `InfoManager.check_playlist_protection(caller_nickname)`:
    - If current `player_name` is empty: Allow.
    - If current `player_name` is an administrator, room owner, or system user: Allow (their playback is unprotected).
    - If `caller_nickname` is an administrator or room owner (`is_human_operator(caller)`): Allow (can override user protection).
    - If `caller_nickname` is the current player or an avatar of the current player: Allow.
    - If current player (or any avatar) is still online:
      - If `caller_nickname` is a system user (Timer, Agent) or normal user: Deny with protection error.
    - If current player and all avatars have left the room: Allow.
- **Sleep Protection Behavior Matrix**:
  - In `CommandManager.process_command`:
    - Command level bypass: Administrators, Room Owner, and configured System Users bypass command level restrictions.
    - Sleep protection check:
      - If `is_human_operator(message_info.nickname)` is true: Sleep check is bypassed (manual human operator override: Room Owner and Admins).
      - If `message_info.sleep_exempt` is true: Sleep check is bypassed (manual @ mention resolution).
      - Otherwise (including automated System Users like `Timer` / `Agent`, and normal attendees): If `SleepManager.is_blocked_command(prefix)` is true, execution is blocked with rest notice.
- **Configuration Structure**:
  - Configurable under `soul.room_owner`, `soul.admin_users`, and `soul.system_users` (with fallback to top-level keys).

## Testing Decisions

- **Good Test Criteria**: Tests must verify externally observable command outcomes, return payloads, and protection states at the highest seams without mocking internal dictionary structures or private variables.
- **Modules Tested**:
  - `CommandManager`: Verify sleep protection and command level enforcement across all roles (Room Owner, Console, Admin, System Users, Normal Users).
  - `InfoManager` / Music Commands (`RadioCommand`, `PlaylistCommand`): Verify playlist takeover permissions and blocks across all permutations of current player role vs. caller role.
- **Prior Art**:
  - `tests/test_playlist_guardian.py`
  - `tests/test_command_manager_sleep_block.py`
  - `tests/test_level_command.py`

## Out of Scope

- Changing Soul App UI drawer administration buttons (handled by `AdminManager`).
- Dynamic database persistence of administrator roles (roles remain managed via yaml configuration files).
- Modifying guest room restrictions (`RoomState.is_guest_room`).

## Further Notes

- Unifying `Console` into `room_owner` ensures consistent privilege resolution across both chat intake and backend console queues.
