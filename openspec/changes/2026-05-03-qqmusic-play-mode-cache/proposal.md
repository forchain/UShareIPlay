## Why

当前 `mode`（播放模式切换）命令每次执行都会切到 QQ 音乐并通过 UI 实时识别/切换模式。由于系统没有记录“当前播放模式”，即使用户连续两次切换到同一模式，也会重复进行 App 切换与 UI 读取，效率低、延迟高。

此外，刚开服/重启后系统也无法知道 QQ 音乐当前处于哪种播放模式，必须通过 UI 才能确认。因此需要一个“默认 unknown + 在合适时机校验自愈”的轻量状态机制，以减少冗余操作并降低状态漂移风险。

## What Changes

- 新增 QQ 音乐播放模式的进程内记录（默认 `unknown`）。
- `mode` 命令在切换成功后写入记录；当请求切换到与记录一致的模式时可直接短路返回“已是该模式”（仅当记录非 unknown）。
- `QQMusicHandler.get_playlist_info()` 在进入“播放列表弹层/列表页”后，利用同一界面可见的三种模式按钮进行一次校验；若发现记录与 UI 识别不一致，自动修正记录（自愈）。
- `info` 命令返回值附带当前记录的播放模式（并保持 unknown 的语义：unknown 下不短路）。

## Capabilities

### New Capabilities

- `qqmusic-play-mode-cache`: 在进程内缓存 QQ 音乐播放模式（unknown/list/single/random），支持写入与读取。
- `qqmusic-play-mode-self-heal`: 在播放列表界面读取模式并自动纠正缓存，降低漂移概率。

### Modified Capabilities

- `mode-command-optimization`: 对播放模式切换命令增加“同模式短路”优化。
- `info-extended`: `info` 输出增加当前播放模式信息。

## Non-Goals

- 不将播放模式持久化到数据库（避免跨重启“记住错误状态”）。
- 不改变现有 `mode` 命令对 unknown 状态的行为：unknown 下必须走 UI 识别/切换。
- 不重构 QQ 音乐整体导航/播放页逻辑，只在现有调用链上增加最小状态记录与校验。

## Acceptance Criteria

- 默认状态为 `unknown`：
  - 刚启动时执行 `mode` 任意模式切换，仍会切到 QQ 音乐并执行 UI 操作（不短路）。
- 一旦 `mode` 切换成功或识别到“已经是目标模式”，系统应记录当前模式。
- 记录为某模式时，再次执行同模式切换：
  - 应直接返回“已经是该模式”，不再切换到 QQ 音乐 UI（短路）。
- 执行任意一次“查看播放列表”（触发 `get_playlist_info()`）时：
  - 应在播放列表界面识别真实模式，并在发现不一致时自动更新记录。
- `info` 返回中应包含当前播放模式（unknown/list/single/random 或中文映射），且不会破坏原有字段。

