# Playback Muting with Adaptive MediaSession Readiness

## Status
Accepted

## Date
2026-09-21

## Context
When UShareIPlay executes music-switching commands (`:play`, `:skip`, `:fav`, `:album`, `:playlist`, `:singer`, `:radio`), the bot navigates QQ Music UI to select a track, switch playlists, or trigger playback. During this transition, audio output momentarily interrupts, loops, or picks up unwanted ambient mic artifacts. Unmuting the bot's Soul microphone too early broadcasts transient UI sounds or silence; waiting too long introduces unnatural silence after the music starts.

## Decision
Implement `PlaybackMuting` as a command execution guard with **adaptive MediaSession readiness**:

1. **Explicit Command Declaration**:
   - Commands that interrupt audio stream state declare `playback_muting = True`.
   - Queuing commands (`:next`) only append to playlists without stopping playback, so they do not participate.

2. **Scoped Lifecycle Guard**:
   - `CommandManager.playback_muting_guard()` wraps the target command execution:
     1. Mute the Soul party microphone (`SoulHandler.mute_mic()`).
     2. Execute the track change operation in QQ Music.
     3. Post command confirmation / song announcement to Soul chat.
     4. Query Android MediaSession state (`dumpsys media_session`) adaptively until playback state reports `STATE_PLAYING` (with song title matching expected song or fallback timeout).
     5. Unmute microphone (`SoulHandler.unmute_mic()`).

3. **Failure Short-Circuiting**:
   - If a command fails during execution (e.g. song not found), `_report_playback_failure()` immediately cancels the readiness wait and restores microphone state without delay.

## Alternatives Considered
- **Fixed `time.sleep(N)`**:
  - *Rejected*: Device performance, network buffering, and app launch times vary from 1s to 8s; fixed sleep is either too short (causing audio burps) or too long (wasting time).
- **UI Element Polling (QQ Music Play Button)**:
  - *Rejected*: The UI button state flips to "pause" well before the audio decoder buffers and pushes PCM to the audio sink. Android MediaSession provides OS-level proof of active playback.

## Consequences
- Clean audio transitions in Soul App party rooms without transient noise or clipped intro audio.
- Resilient against slow network buffering or immediate command failures.
- Non-blocking to steady-state background music playback.
