# Design Spec: Playback Muting and Adaptive MediaSession Readiness Guard

**Issue:** [#297](https://github.com/forchain/UShareIPlay/issues/297)  
**Tracked Tickets:** [#298](https://github.com/forchain/UShareIPlay/issues/298), [#299](https://github.com/forchain/UShareIPlay/issues/299), [#300](https://github.com/forchain/UShareIPlay/issues/300)  
**Date:** 2026-09-21  
**Status:** Ready for Implementation  

## Problem Statement

When the bot plays or switches songs in Soul App party rooms (via `:play`, `:next`, `:skip`, `:playlist`, `:album`, `:singer`, `:fav`, or `:radio`), an audible pop, crackle, or static noise occurs across the room's voice channel. This noise is caused by an unstable intermediate playback state while QQ Music buffers, reinitializes the audio stream, or switches app contexts while the microphone is active.

In host-owned rooms, this issue is rarely noticed because attendees seldom occupy mic slots. However, when the bot is invited into other users' party rooms (Guest Room mode), multiple attendees are frequently active on mic. In this context, the noise bursts disrupt ongoing conversations, degrade user experience, and reflect poorly on the bot's stability.

Currently, `BaseCommand` eagerly forces the microphone ON (`ensure_mic_active`) *before* executing song search and playback UI actions, leaving the mic live throughout the entire loading and buffering window. Furthermore, fixed timer delays are brittle across diverse network conditions and device performance, either unmuting too early (leaking noise) or unmuting too late (delaying audible playback).

## Solution

Introduce a unified **Playback Muting** lifecycle with adaptive readiness detection:

1. **Pre-Playback Silence Guard**:
   - Before dispatching any song-switching operation, the bot checks its current mic state. If the microphone is active, it mutes the mic (闭麦) before leaving Soul App or issuing playback keys.
   - If the bot is already muted or not seated on mic, no redundant UI actions are performed.

2. **Parallel Playback Execution & In-Room Completion**:
   - The bot executes the song search, queueing, or skipping in QQ Music.
   - The bot switches back to Soul App and sends the public room notification (e.g. `[10:00:00] 正在播放：xxx @user`). The UI typing and message dispatch latency naturally overlaps with QQ Music's initial buffering window.

3. **Adaptive MediaSession Readiness Wait**:
   - Rather than guessing a static sleep delay, the bot polls Android's underlying `dumpsys media_session` via ADB.
   - It verifies that the `PlaybackState` transitions to `state=3 (Playing)` and the active track metadata corresponds to the newly selected song.
   - Includes a safe timeout fuse (default 5.0s) and a short 0.3s audio hardware settling buffer.

4. **Guaranteed Post-Playback Unmute Recovery**:
   - Once playback readiness is confirmed (or upon timeout fallback), the bot restores microphone activity (`ensure_mic_active`).
   - The unmute recovery is guaranteed in a `finally` block, ensuring that even if search fails, a network error occurs, or VIP restrictions block playback, the bot never remains permanently silenced.

5. **Configurable Scope (Guest Room Aware)**:
   - Configuration allows enabling Playback Muting globally (`always`) or scoping it specifically to guest rooms (`guest_room_only: true`), ensuring zero friction in private rooms while offering full noise protection in external party rooms.

## User Stories

1. As a room attendee in a shared party room, I want the bot to remain silent while changing songs, so that I do not hear bursts of static, crackle, or audio glitches while talking on mic.
2. As a party room host who invited the bot, I want attendees' vocal interactions uninterrupted during song selection, so that the bot feels like a professional, polished music player.
3. As a room attendee requesting a song via `:play`, I want to see the playback confirmation message on screen without waiting for artificial lag, so that I know my request was received promptly.
4. As a bot administrator, I want playback readiness detected through genuine Android MediaSession status rather than brittle hardcoded sleep delays, so that unmuting adapts automatically to fluctuating network and device speeds.
5. As a bot operator, I want the bot to automatically recover and unmute if a song fails to load or times out after 5 seconds, so that the bot's microphone does not stay stuck in a closed state.
6. As a room attendee using `:next` or `:skip`, I want the microphone closed during the skip transition and reopened once the next track is confirmed playing, so that track switching is seamless.
7. As a room attendee requesting an album or singer playlist via `:album` or `:singer`, I want the muting protection applied to playlist-initialization actions, so that multiple-song starts do not pop.
8. As a bot operator, I want to configure whether playback muting applies globally or only in guest rooms (`guest_room_only`), so that I can tailor behavior to my deployment scenario.
9. As a bot operator, I want default settings that work out of the box (`enabled: true`, `guest_room_only: false`, `timeout: 5.0`), requiring zero mandatory configuration tweaks.
10. As an attendee requesting a track when the bot is already muted, I want the bot to proceed with playback and unmute when the song is ready, fulfilling my song request without extra mic toggling.
11. As an attendee whose requested song is not found or VIP-restricted, I want the bot to report the error in chat and immediately restore the mic, so that room conversation can resume without disruption.
12. As a room attendee, when a song finishes buffering and starts playing, I want a 0.3-second settling delay before unmuting, so that audio driver DAC initialization clicks are never broadcast over the mic.
13. As a developer, I want all playback-altering commands (`:play`, `:next`, `:skip`, `:playlist`, `:album`, `:singer`, `:fav`, `:radio`) to share a single muting contract, avoiding duplicated mic-toggling logic across command classes.

## Implementation Decisions

- **Playback Muting Protocol & Context Manager**:
  - Encapsulate the muting lifecycle in a dedicated coordinator or async context manager (e.g. `playback_muting_context`).
  - Responsibilities:
    1. Pre-condition evaluation: check `is_guest_room` and configuration flags (`enabled`, `guest_room_only`). If disabled, yield directly without toggling.
    2. Silence phase: inspect current mic state via `element_finder` (`toggle_mic` content-desc). If open (`闭麦按钮`), trigger click to mute.
    3. Yield control to execute command playback and room message dispatch.
    4. Readiness phase: poll `MusicManager.wait_for_playback_ready(expected_song, timeout=5.0)`.
    5. Re-activation phase: invoke `SoulHandler.ensure_mic_active()` to un-mute and ensure seat mic engagement.
    6. Fault recovery: wrap in `try...finally` so re-activation executes even if exceptions are raised during playback or readiness polling.

- **MediaSession Readiness Inspection in MusicManager**:
  - Extend `MusicManager` with `wait_for_playback_ready(expected_song: Optional[str] = None, timeout: float = 5.0, settling_delay: float = 0.3) -> bool`.
  - Polling interval: 0.3s.
  - Success criteria:
    - `dumpsys media_session` reports `PlaybackState {state=3` (`Playing`).
    - If `expected_song` is provided, current metadata `song` matches or reflects the updated track (discarding stale metadata from the previous track).
  - Once `state=3` is verified, sleep for `settling_delay` (0.3s) before returning `True`.
  - On timeout: log a warning and return `False`, triggering immediate unmute in the caller.

- **Deprecation of Eager `BaseCommand.requires_mic` Prelude**:
  - Previously, `BaseCommand.process` invoked `self.soul_handler.ensure_mic_active()` *prior* to `do_process` if `requires_mic = True`.
  - In the new design, commands that perform playback delegate microphone lifecycle management to the Playback Muting coordinator. Eager prelude mic activation during playback is eliminated.

- **Configuration Schema**:
  - Added under `soul.playback_mute` in `config.yaml`:
    ```yaml
    soul:
      playback_mute:
        enabled: true
        guest_room_only: false
        timeout: 5.0
        settling_delay: 0.3
    ```
  - Safe defaults provided in code if keys are omitted.

## Testing Decisions

- **What makes a good test**:
  - Tests must verify external observable behavior: the invocation sequence of mic mute, command execution, message dispatch, ADB polling, and mic unmute.
  - Tests must not couple to internal sleep loops, instead using injectable clocks, mocks, or async timeouts.
- **Modules to test**:
  - `PlaybackMuting` lifecycle orchestration:
    - Normal successful playback: verifies sequence `mute -> do_process -> dispatch_message -> wait_ready -> unmute`.
    - Guest room filtering: verifies muting skipped when `guest_room_only: true` and `is_guest_room: false`.
    - Error resilience: verifies mic is unmuted when `do_process` raises an exception or search fails.
    - Timeout resilience: verifies mic is unmuted when MediaSession polling times out.
    - Initial state awareness: verifies no mute click attempted if already muted.
  - `MusicManager.wait_for_playback_ready`:
    - Tests with mocked ADB `dumpsys media_session` outputs: transitioning from `state=6` (Buffering) or old song to `state=3` (Playing) with target song title.
    - Tests timeout behavior when state remains `state=2` or `state=6`.
- **Prior art**:
  - `tests/test_base_command_wrapper.py`: mock controller and handler assertions.
  - `tests/test_guest_room_guard.py`: mock `RoomState.is_guest_room` assertions.
  - `tests/test_music_manager.py`: mock driver shell script executions.

## Out of Scope

- Audio digital signal processing (DSP) or direct soundcard loopback muting at the Linux ALSA / PipeWire / macOS BlackHole driver level.
- Background natural track transitions in QQ Music when the app remains untouched in the background (no UI switching occurs; the noise bug is tied to active app switching and explicit track initialization).
- Soul App microphone volume level adjustments (only binary mute/unmute toggle is managed).

## Further Notes

- The 0.3s audio settling delay after `state=3` is verified accounts for initial PCM decoding ramp-up on Android virtual and physical audio interfaces.
- The default timeout of 5.0s is deliberately bounded so that attendees never experience more than a momentary silence even during severe network slowdowns.
