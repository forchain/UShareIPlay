# Playback Muting with Adaptive MediaSession Readiness

## Status
Accepted

### Status note (2026-09-25)
The microphone side of this ADR is provided by `MicManager`, whose seam is
`state()` / `set_active(bool)` / `ensure_active()`:

- `state()` returns `True` open / `False` muted / `None` unreadable, reading the
  mic toggle's `content-desc` ("闭麦按钮" = open).
- `set_active()` owns the seat invariant: opening the mic first ensures the bot
  holds a seat, because the room only offers a grab-mic entry while off-seat.
- `ensure_active()` is the guaranteed restore this guard's step 5 uses.

Before this, `PlaybackMuting` declared mic UI state to be "provided by
SoulHandler" — true only for its own copy of the reader. The same `content-desc`
read and the same seat pre-check existed in three diverging implementations
(`PlaybackMuting`, `:mic`, `SoulHandler.ensure_mic_active`); this note makes the
seam universal rather than contradicting the decision above. Steps 1 and 5 below
are implemented as `MicManager.set_active(False)` and `MicManager.ensure_active()`.

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
     1. Mute the Soul party microphone (`MicManager.set_active(False)`; see the status note below).
     2. Execute the track change operation in QQ Music.
     3. Post command confirmation / song announcement to Soul chat.
     4. Query Android MediaSession state (`dumpsys media_session`) adaptively until playback state reports `STATE_PLAYING` (with song title matching expected song or fallback timeout).
     5. Unmute microphone (`MicManager.ensure_active()`).

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
