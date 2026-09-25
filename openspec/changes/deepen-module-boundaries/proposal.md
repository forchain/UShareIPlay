## Context

An architecture review of the last 40 commits (hot spots: `app_controller`, `party_manager`, `command_manager`, `chat_intake`, the music commands) found eight places where a seam exists but production code has not moved to it, or where "one module's job" is spread across several callers as near-identical ritual code. The through-line is the same in every case: an interface is named, the behavior behind it is real, and the callers still reach past it.

Cross-cutting evidence from the review: 13 playlist-sync blocks · 5 tab-selector copies · 3 mic content-desc readers · 2 enter-banner parsers · 3 cooldown state machines · ~90 hand-rolled wait→click pairs across 24 files · 192 direct `QQMusicHandler` references from music commands vs 8 `MusicManager` calls.

Each candidate below is justified by the **deletion test**: delete the duplicated call-site code and complexity would either concentrate in an existing deep module (the refactor is correct) or reappear nowhere (the call-site code is a pass-through and the seam is the real owner).

## Goals / Non-Goals

**Goals:**
- Land the eight deepening candidates in review priority order, each as its own verified commit
- Move production callers onto seams that already exist and are already tested
- Delete duplicated ritual code so each behavior has exactly one owner
- Convert white-box tests that assert on mocked call arguments into interface-level tests

**Non-Goals:**
- Do not change observable bot behavior (chat responses, playback, room state) — these are structural refactors
- Do not invent new seams where the review did not identify one
- Do not redesign module interfaces that callers already use correctly
- Do not batch candidates into one commit; each must be independently revertible

## Decisions

### 决策 1: 完成 music-adapter tab seam (候选 1, 最高优先级)

**选择**: 将 `album.py` / `singer.py` / `playlist.py` / `lyrics.py` 里四处手写的 tab 滚动 ritual 和 `QQMusicHandler.select_song_tab` 里手写的滑动几何，全部迁移到已存在的 `select_tab()` seam；命令通过 `MusicManager.select_tab()` 调用。

**理由**:
- `select_tab` 已由 commit `afe2b50` 建成并有 235 行测试，但**零生产调用者** —— 这是全仓最便宜的 deepening
- 五个副本已经漂移（swipe 预算 10 对 20；没有一处有 stale-element 恢复）
- `select_song_tab` 的唯一特例是"向回滚到第一个 tab"，可以折叠成 `direction="right"` 参数
- 迁移是机械的、纯删除的，且立刻杀掉 `test_singer_command` / `test_lyrics_command` 里对 mock 滚动参数的 white-box 断言

**swipe 预算的处理**: 预算收敛到 `config.yaml` 的 `qq_music.tab_max_swipes` 单一位置，取 20（`lyrics` tab 位于最右、生产上确实需要 20 次；其余 tab 受 `scroll_container_until_element` 的边界早退保护，更高的上限不会带来额外滑动）。

### 决策 2: PlaylistAdoption 深模块 (候选 2)

**选择**: 新建 `PlaylistAdoption`，接口为 `guard_switch(requester) → error?` 与 `adopt(mode, title, topic, playlist)`；六个音乐命令的 13 个五连写块收缩为 query → adopt。

**理由**: "房间切歌单后发生什么"目前散落在六个命令文件里，写序只存在于 `radio` 的注释中，`topic.split("-")` 存在三套规则，`list_mode` 是裸可变状态。ADR-0004 记录的 facade 泄漏正由此产生 —— `adopt()` 成为 facade 的调用者，facade 保持纯委托。

### 决策 3: 聊天 intake 收回 enter/return 横幅文法 (候选 3)

**选择**: `Chat Intake` 增加 `classify_banner_line()`（吸收 点赞 家族）；`FollowerMessageEvent` 只保留 UI 动作。

**理由**: `CONTEXT.md` 已声明 Chat Intake 拥有正则家族，但 `_parse_message` 逐字符复制了同一套 enter/return 文法，且两份在 return-vs-enter 上已经不一致。Soul 文案变更现在必须改两处。

### 决策 4: RoomInfoWindow 成为真模块 (候选 4)

**选择**: 新建 `RoomInfoWindow`，接口为 `with_window_open()` + `audit_and_repair()`，拥有打开检测、关闭兜底、以及"在窗口内同步"的顺序约束；四个 manager 只保留各自字段的编辑。

**理由**: 同一个对话框 ritual 被四份复制，关闭靠 `PartyManager` 的 `finally` 兜底，`_update_title_ui` 在编辑中途伸手到 `RecommendationManager` / `PartyManager`。顺序注释应成为被强制的接口。

### 决策 5: 单一 mic 深模块 (候选 5)

**选择**: 新建 mic 模块，接口为 `state()` / `set_active(bool)` / `ensure_active()`，折叠"mic on = content-desc 闭麦按钮"与"扩容前先上麦"两个不变量；`playback_muting`、`:mic`、`pause`、`ui_actions` 全部改走该接口。

**理由**: 同一状态读取存在三份分歧实现，而名字最相关的 `MicManager` 是仓库里最浅的模块（盲点击，`get_mic_status` 会 NameError）。ADR-0007 把 mic UI 状态声明为 "provided by SoulHandler"，只对其中一份副本成立。

### 决策 6: MessageManager 以接口暴露聊天窗口观察 (候选 6)

**选择**: `observe(content_list) → ChatDelta` 拥有 diff / 漏检 / anchor 兜底；一个 `dispatch()` 同时服务 live 与 missed 路径；房主解析改走 `RolePolicy`。

**理由**: 事件对象通过两个公有 deque 反向执行 manager 的职责，并知道它们的 `maxlen`；gift 处理与房主解析在 live/missed 两条路径上各有一份。当前每个 chat-flow 测试都必须 `monkeypatch MessageManager._instance` —— 因为接口本身没有可测之处。

### 决策 7: RoomName / Notice / Topic 冷却之下的 pending-write 内核 (候选 7)

**选择**: 一个参数化的 `PendingWrite(cooldown_min, apply)` 内核，由三个 manager 各自持有；manager 仍然是面向调用方的 seam，只有计时机制下沉。

**理由**: 三份同一状态机、三套微妙不同的语义（时钟何时推进、冷却多久），加上四份命令侧 flush 映射。按 ADR-0001 的逻辑执行（其诊断正是"冷却/pending 编排重复"），但必须框架为 `RoomNameManager` 之下的私有内核，而非对 Room Name 不变量的重新拆分。

### 决策 8: 从 AppController 循环中抽出运行时输入管线 (候选 8)

**选择**: 注入式 `RuntimeInputPipeline.drain()` 拥有 console/agent 归一化、queue 文法、静默/私聊路由与 meta-commands；`_detect_initial_room_state` 与 `RoomIdEvent` 合并为一个 `verify_current_room()`；启动期 I/O 走已抽出的 `DriverLifecycle` 模式。

**理由**: 监控循环第二次施加 queue 文法（`CommandManager` 已经有），`_detect_initial_room_state` 是 `RoomIdEvent` 的副本，构造函数的设备 I/O 迫使测试使用 `AppController.__new__` 并手工拼装 12 个字段。此项放在候选 1–3 之后做，因为它们会先缩小循环必须知道的上下文。

## Risks & Mitigations

- **行为回归风险（`direction="right"` 与 `tab_max_swipes=20`）**: 二者的目标值都取自生产代码里"已知可用"的那一份副本，而不是新猜的值；`scroll_container_until_element` 的页面哈希边界早退保证更高的上限不会造成额外滑动。
- **顺序敏感的重构（候选 2/4/7）**: 写序当前只存在于注释里。重构时必须先把顺序写成接口的一部分（参数化或显式调用点），再删除旧块，否则会把隐式顺序变成显式 bug。
- **测试在重构中失去保护力**: 若干现行测试断言的是 mock 调用参数（white-box）。迁移时同步改写为接口级断言，而不是删除后留空。
- **候选之间互相影响**: 候选 1–3 会改变候选 8 循环必须知道的上下文，因此 8 排在最后；候选 2 与 1 相邻（同为音乐 seam），但各自独立提交。

## Success Criteria

- 每个候选对应一个独立 commit，提交信息说明删除了什么、复杂性集中到了哪里
- 全量 `uv run pytest -q` 在每个 commit 上通过
- 每个候选的"deletion test"可被演示：删除重复块后，行为只在深模块里存在
