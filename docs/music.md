---
covers: [QQMusicHandler, MusicManager, PlayCommand, FavCommand, SkipCommand, NextCommand, PauseCommand, VolCommand, ModeCommand, AccCommand, KtvCommand, LyricsCommand, SingerCommand, AlbumCommand, PlaylistCommand, RadioCommand, InfoCommand]
last-synced: 2026-03-23
---

## Overview

Music playback is controlled via QQ Music, automated through `QQMusicHandler`. `MusicManager` provides the high-level API used by commands. All music state (current song, mode, volume) is read live from the QQ Music UI.

## Components

| Component | Responsibility |
|---|---|
| `QQMusicHandler` | Direct QQ Music UI automation (search, play, skip, lyrics OCR, accompaniment) |
| `MusicManager` | High-level music operations; holds current song state; called by commands |
| `src/commands/play.py` … `radio.py` | One file per music command, each calls MusicManager |

## How It Works

1. Commands are received in Soul App chat → `CommandManager` dispatches to the relevant command class.
2. The command calls `MusicManager`, which calls `QQMusicHandler`.
3. `QQMusicHandler` switches focus to QQ Music via Appium, performs UI actions, then switches back to Soul App.
4. Result (song name, error) is sent back to Soul App chat via `MessageManager`.

**App switching** uses `AppController.driver` with `activate_app(package_name)`. The UI lock (`AppController.ui_lock`) prevents concurrent UI access.

**KTV / lyrics**: `LyricsCommand` uses Tesseract OCR via `pytesseract` to read lyrics from the QQ Music screen.

**Accompaniment mode**: Toggles the QQ Music K-song (伴唱) mode via a settings menu; state is read from the button content-desc.

## Commands

| Prefix | Level | Params | Description |
|---|---|---|---|
| `play` | 1 | `<song> [artist]` | Search and play immediately |
| `next` | 0 | `<song> [artist]` | Add to play queue |
| `fav` | 1 | `[0 language]` | Play from favourites; optional language filter |
| `skip` | 1 | — | Skip to next song |
| `pause` | 1 | `[0/1]` | Resume (0) or pause (1); toggles if no param |
| `vol` | 1 | `[0-15]` | Set volume; shows current if no param |
| `mode` | 2 | `0/1/-1` | Playback mode: 0=list, 1=single, -1=random |
| `acc` | 2 | `[0/1]` | Toggle accompaniment (伴唱) mode |
| `ktv` | 1 | `[0/1]` | Toggle KTV mode (shows OCR lyrics in chat) |
| `lyrics` | 1 | — | Post current song lyrics to chat |
| `singer` | 1 | `<name>` | Play all songs by artist |
| `album` | 2 | `<name>` | Play entire album |
| `playlist` | 2 | `<name>` | Play a named playlist |
| `radio` | 2 | `guess/daily/collection/sleep` | Play a radio station |
| `info` | 0 | — | Show current song, queue, online users, timers |

## Data Model

No DB model — music state is read live from QQ Music UI. `MusicManager` caches `current_song` and `current_singer` in memory.

## Extension Points

- **New music source**: Add method to `QQMusicHandler`, expose via `MusicManager`, create new command in `src/commands/`.
- **New command**: Create `src/commands/<name>.py` inheriting `BaseCommand`, implement `execute()`. No registration needed — `CommandManager` auto-discovers via dynamic import.
