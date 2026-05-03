## Overview

为 QQ 音乐的“播放模式”（顺序/单曲/随机）引入进程内状态记录，减少 `mode` 命令的冗余 App 切换与 UI 读取。同时通过 `get_playlist_info()`（播放列表界面）顺手做一次校验，实现状态自愈，降低“记录与真实状态不一致”的风险。

## Current State

- `ModeCommand` 每次执行都会 `switch_to_app()` 并通过 `play_mode_*` 元素识别当前模式；如果已是目标模式则直接返回，但不会记录到全局状态。
- `QQMusicHandler.get_playlist_info()` 会切到 QQ 音乐并进入播放列表界面读取列表信息；该界面可见播放模式按钮（由 XPath `//android.widget.ImageButton[@content-desc="随机播放"/"顺序播放"/"单曲循环"]` 判定）。
- `InfoCommand` 从 `InfoManager` 读取缓存并返回展示信息，目前不包含播放模式。

## Proposed Design

### 1) In-memory state in `QQMusicHandler`

新增字段：

- `QQMusicHandler.play_mode_key: str`，取值：
  - `unknown`（默认）
  - `list`（顺序播放）
  - `single`（单曲循环）
  - `random`（随机播放）

并提供一个稳定的显示映射（用于返回/日志）：

- `list` → `顺序播放`
- `single` → `单曲循环`
- `random` → `随机播放`
- `unknown` → `未知`

### 2) `mode` command: write-through + short-circuit

在 `ModeCommand` 中：

- 当 UI 识别出 `current_mode == target_mode`（already_target）时：
  - 写入 `QQMusicHandler.play_mode_key = <target>`
  - 返回“已经是xxx模式”
- 当 UI 点击切换并确认达到目标模式时：
  - 写入 `QQMusicHandler.play_mode_key = <target>`
  - 返回“成功切换到xxx模式”

短路逻辑：

- 若 `QQMusicHandler.play_mode_key != unknown` 且请求目标与记录一致：
  - 直接返回“已经是xxx模式”
  - 不调用 `switch_to_app()`，避免切换/读取开销
- 若记录为 `unknown`：
  - 不短路，保持现有 UI 识别/切换流程

### 3) Self-heal on playlist UI (`get_playlist_info`)

在 `QQMusicHandler.get_playlist_info()`：

- 进入播放列表界面后，执行一次“播放模式识别”：
  - 通过等待任一模式按钮出现来判定模式（list/single/random）
  - 若与 `play_mode_key` 不一致，则记录 warning 日志并更新缓存为识别到的模式

该校验不应影响 `get_playlist_info()` 的主功能：

- 若模式按钮未能识别（超时/偶发 UI 异常）：
  - 不抛出错误，不阻断播放列表读取
  - 只记录日志（或保持静默，视现有日志噪音策略）

### 4) `info` output

在 `InfoCommand.process()` 的返回 dict 中追加：

- `play_mode_key`: `unknown|list|single|random`
- `play_mode`: 中文映射（未知/顺序播放/单曲循环/随机播放）

保持原有字段不变，且 unknown 状态也应可展示为“未知”。

## Configuration / Selectors

为避免硬编码 XPath，播放列表界面的三种模式按钮应通过 `config.yaml` 的 element key 管理（复用或新增 key）：

- `play_mode_random`: `//android.widget.ImageButton[@content-desc="随机播放"]`
- `play_mode_list`: `//android.widget.ImageButton[@content-desc="顺序播放"]`
- `play_mode_single`: `//android.widget.ImageButton[@content-desc="单曲循环"]`

要求：这些 key 在“播放列表弹层/列表页”可命中。

## Edge Cases & Decisions

- **unknown 的语义**：unknown 下不做短路；任何更新/切换都必须走 UI。
- **漂移与自愈**：用户手动在 QQ 音乐里更改模式，可能导致缓存过时；一旦系统执行一次“查看播放列表”，即可利用同 UI 校验并自愈。
- **一致性与性能**：短路以性能为主，自愈以正确性为主；两者结合避免频繁切 App，同时给出可接受的纠偏路径。

