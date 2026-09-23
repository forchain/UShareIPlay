# Design Spec: Fix Playlist Separator Parsing and Full-Width Unicode Character Handling

**Date:** 2026-09-04  
**Status:** Ready for Implementation  

## Problem Statement

When a party room user triggers playback of a playlist whose title contains full-width separators—such as the standard Chinese IME full-width vertical line `｜` (`U+FF5C`) seen in `方力申｜小方45首經典好歌`—the bot fails to split the playlist name into subject and topic. Instead of setting the room title to the playlist subject (e.g. `方力申`) and the room topic to the playlist focus (e.g. `小方45首經典好歌`), the parsing step fails silently and logs `Failed to parse playlist topic`. The room title is consequently set to the unparsed playlist name (truncated by length limits to `方力申｜小方45首經典好`), and the room topic erroneously falls back to unrelated UI subtext or tags from the music search card (such as `广东话`). Furthermore, downstream sanitization in room name and topic managers only strips ASCII half-width delimiters, leaving full-width punctuation unhandled if unparsed text leaks through.

## Solution

Normalize and expand separator recognition in the playlist parsing subsystem to comprehensively support full-width Unicode characters, particularly full-width vertical lines (`U+FF5C`), CJK radical vertical bars (`U+4E28`), full-width dashes, and authentic Chinese quotation marks (`“”‘’`). When a playlist containing full-width separators is selected, the parser cleanly divides it into a distinct subject (applied to Room Name via `RoomNameManager`) and topic (applied to room topic via `TopicManager`). Downstream title and topic sanitization is hardened to recognize both full-width and half-width separators.

## User Stories

1. As a party room listener, I want playlists with Chinese full-width vertical line separators (e.g. `歌手｜歌单名`) to split into the singer as room title and the collection name as room topic, so that room participants immediately see what is being played.
2. As a party room host, I want the bot to avoid setting room title to an unparsed, truncated string with trailing separators (e.g. `方力申｜小方45首經典好`), so that the room title looks polished and professional.
3. As a party room participant, I want the room topic to reflect the specific theme of the active playlist rather than unrelated UI category tags (such as "广东话"), so that I understand the playlist context.
4. As a bot operator, I want playlist names with half-width vertical pipes (`|`), full-width pipes (`｜`), and CJK ideographic strokes (`丨`) to be parsed reliably, so that user searches work identically regardless of which separator symbol was typed by the playlist creator.
5. As a bot operator, I want playlists using Chinese brackets (`【】`, `《》`, `「」`, `（）`) to cleanly separate their outer tag from their inner topic, so that bracketed playlist titles are correctly classified.
6. As a bot operator, I want playlists using various dash types (en dash, em dash, hyphen-minus, fullwidth hyphen) to separate title and topic predictably.
7. As a party room listener, I want leading, trailing, and enclosing Chinese quotation marks (`“”`, `‘’`) to be trimmed cleanly from extracted subjects and topics, so that titles do not have dangling punctuation.
8. As a developer, I want downstream room title and topic managers to handle both full-width and half-width delimiters defensively, so that even if unparsed text reaches them, redundant delimiters are stripped before writing to the UI.
9. As a developer, I want clear regression tests covering full-width Unicode separators, so that future refactorings do not reintroduce silent parsing failures.
10. As a party room operator, I want playlists with no separators to continue using the playlist title as the room title and falling back to search card subtext for the topic, preserving existing graceful degradation.

## Implementation Decisions

- **Pure Parsing Seam (Highest Seam)**:
  - Update `PlaylistParser` to include `U+FF5C` (`｜`, FULLWIDTH VERTICAL LINE) at top priority in `separators`.
  - Retain `U+4E28` (`丨`, CJK UNIFIED IDEOGRAPH-4E28) and `U+007C` (`|`, ASCII pipe) for backwards and variant compatibility.
  - Expand `strip_chars` in `PlaylistParser` to include proper Chinese quotation marks (`“`, `”`, `‘`, `’`) instead of duplicate ASCII quotes.
  - Include full-width hyphen/dash variants (`－`, `—`, `–`).
- **Downstream Defense-in-Depth Sanitization**:
  - In `RoomNameManager.set_next_title` and `TopicManager.change_topic`, replace single-character ASCII `split('|')` and `split('(')` with normalization or splitting on both half-width and full-width delimiters (`|`, `｜`, `(`, `（`).
- **Cohesion with Room Name ADR (ADR-0001)**:
  - Respect `RoomNameManager` as the single owner of the `{theme}｜{title}` invariant, ensuring the parsed subject is passed cleanly without double-prefixing.

## Testing Decisions

- **Good Test Criteria**:
  Tests must assert external observable behavior (input string -> expected subject and topic tuple) across a wide range of real-world playlist title strings without mocking Appium or UI elements.
- **Modules Tested**:
  - `ushareiplay.helpers.playlist_parser`
  - `ushareiplay.managers.room_name_manager`
  - `ushareiplay.managers.topic_manager`
- **Prior Art**:
  - `tests/test_playlist_response_format.py`
  - `tests/test_room_name_manager.py`

## Out of Scope

- Rewriting Appium UI scraping for QQ Music playlist search result items.
- Changing the Soul App UI cooldown rules or room title prefix convention.
- Redesigning the fallback tag extraction when a playlist title genuinely has no delimiter.

## Further Notes

None.
