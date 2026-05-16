# Design Spec: Song Broadcast Toggle & Info Command Update

## Overview
Add a configuration option to toggle automatic broadcasting of current song information when it changes, and include current song information in the output of the `info` command.

## Goals
- Allow users to enable/disable automatic song change notifications via `config.yaml`.
- Enhance the `info` command to provide the currently playing song's details.

## Proposed Changes

### 1. Configuration (`config.yaml`)
- Add `broadcast_playing_info` (boolean) under the `soul:` section.
- Default to `true` to maintain existing behavior if desired, but providing the toggle is the key.
- Update `info` command `response_template` to include `{song} - {singer} • {album}` at the bottom.

### 2. InfoManager (`src/ushareiplay/managers/info_manager.py`)
- Modify `send_playing_message()` to check the `broadcast_playing_info` configuration flag.
- Ensure the logic respects this flag before calling `self.handler.send_message()`.

### 3. InfoCommand (`src/ushareiplay/commands/info.py`)
- The `InfoCommand` already returns `song`, `singer`, and `album` keys in its result dictionary.
- No changes needed to the Python code of `InfoCommand`, as the template update in `config.yaml` will handle the display.

## Verification Plan

### Automated Tests
- Create or update a test case to verify that `InfoManager` correctly reads the `broadcast_playing_info` config.
- Mock `SoulHandler.config` and verify `send_playing_message` behavior for both `true` and `false` states.

### Manual Verification
- Start the app with `broadcast_playing_info: true` and change a song; verify message is sent.
- Start the app with `broadcast_playing_info: false` and change a song; verify NO message is sent.
- Run the `info` command and verify the current song info is displayed at the bottom of the response.
