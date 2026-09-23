---
covers: [QQMusicHandler, MusicManager, PlaybackMuting, PlayCommand, FavCommand, SkipCommand, NextCommand, PauseCommand, VolCommand, ModeCommand, AccCommand, LyricsCommand, SingerCommand, AlbumCommand, PlaylistCommand, RadioCommand, InfoCommand]
last-synced: 2026-09-23
---

## Overview

Music playback is controlled via QQ Music, automated through `QQMusicHandler`. `MusicManager` provides the high-level API used by commands, and `PlaybackMuting` guards audio transitions. All music state (current song, mode, volume) is read live from QQ Music UI and Android MediaSession.

## Components

| Component | Responsibility |
|---|---|
| `QQMusicHandler` | Direct QQ Music UI automation (search, play, skip, lyrics OCR, accompaniment mode) |
| `MusicManager` | High-level music operations; holds current song state; enforces song quality policies |
| `PlaybackMuting` | Mutes microphone during song switching, polls MediaSession for active playback, then restores mic |
| `src/ushareiplay/commands/play.py` … `radio.py` | Command handlers that invoke `MusicManager` |

## How It Works

1. Commands are received in Soul App chat or via `@我` natural language translation.
2. `CommandManager` dispatches to the corresponding command class.
3. For track-switching commands (`play`, `skip`, `fav`, `album`, `playlist`, `singer`, `radio`), execution runs inside `PlaybackMuting.guard()`:
   - Soul App microphone is muted (`SoulHandler.mute_mic()`).
   - QQ Music performs the track switch.
   - Command posts response to Soul App chat.
   - Background polling checks Android MediaSession (`dumpsys media_session`) adaptively until playback state reports `STATE_PLAYING`.
   - Soul App microphone is safely unmuted (`SoulHandler.unmute_mic()`).
4. Queuing commands like `:next` only append tracks without interrupting current playback and do not trigger muting.

### Song Quality Policy & On-Demand Intent
- `MusicManager` automatically filters low-quality tracks (old songs per `old_song_filter`, DJ/Remix noise, singer-mode heuristics) when radio stations or auto-playlists advance.
- An explicit user request (`:play <song>` or `:next <song>`) registers an on-demand intent (`MusicManager.mark_on_demand`), exempting the user's chosen song from the old-song filter for that play. Once the song finishes, standard filtering resumes.

### Lyrics & Accompaniment
- **Lyrics (`:lyrics`)**: Fetches current song lyrics from QQ Music and posts them to Soul App chat in timed segments.
- **Accompaniment (`:acc [0/1]`)**: Toggles QQ Music K-song accompaniment (伴唱) mode via the playback settings menu; state is read from element content-description.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `play` | 1 | `<song> [artist]` | Search and play immediately (with mic muting protection) |
| `next` | 0 | `[<song>] [artist]` | Add to play queue (no params skips to next queued song) |
| `fav` | 1 | `[0 language]` | Play from favorites; optional language filter |
| `skip` | 1 | — | Skip current song |
| `pause` | 1 | `[0/1]` | Resume (0) or pause (1); toggles if no param |
| `vol` | 1 | `[0-15]` | Set volume (0-15); shows current volume if no param |
| `mode` | 2 | `0/1/-1` | Playback mode: 0=list, 1=single loop, -1=random |
| `acc` | 2 | `[0/1]` | Toggle accompaniment (伴唱) mode |
| `lyrics` | 1 | — | Post current song lyrics to chat |
| `singer` | 1 | `<name>` | Play top songs by artist |
| `album` | 2 | `<name>` | Play entire album |
| `playlist` | 2 | `<name>` | Play a named playlist |
| `radio` | 2 | `guess/daily/collection/sleep` | Play recommended radio station |
| `info` | 0 | — | Show current song, queue, online users, and timers |

## Extension Points

- **New music source**: Add UI interaction methods to `QQMusicHandler`, expose them through `MusicManager`, and create a new command in `src/ushareiplay/commands/`.
- **New command**: Create `src/ushareiplay/commands/<name>.py` subclassing `BaseCommand`, implement `do_process()`. If it interrupts playback, set `playback_muting = True`. Auto-discovered by `CommandManager`.
