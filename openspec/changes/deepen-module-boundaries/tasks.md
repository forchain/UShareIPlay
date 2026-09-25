## 1. Music-adapter tab seam (候选 1 · Strong · ports & adapters · 最高优先级)

目标：五处手写 tab-selection ritual 全部改走 `select_tab()`，删除副本；swipe 预算只存在于一处。

- [x] 1.1 `QQMusicHandler.select_song_tab` 的唯一特例折叠为参数：调用点改为 `self.select_tab("song", direction="right")`，删除 `select_song_tab` 方法及其手写滑动几何
- [x] 1.2 `config.yaml` 的 `qq_music.tab_max_swipes` 从 10 提升到 20，并加注释说明该值是最右 tab（歌词）所需的上限
- [x] 1.3 `BaseCommand` 增加懒加载 `music_manager` 属性（沿用 `info_manager` / `room_name_manager` 的既有模式），让音乐命令有一个面向 `MusicManager` 的 seam
- [x] 1.4 `commands/album.py`：删除 `select_album_tab()`，改为 `self.music_manager.select_tab("album")`
- [x] 1.5 `commands/singer.py`：删除 `select_singer_tab()`，改为 `self.music_manager.select_tab("singer")`
- [x] 1.6 `commands/playlist.py`：删除 `select_playlist_tab()`，改为 `self.music_manager.select_tab("playlist")`
- [x] 1.7 `commands/lyrics.py`：删除 `select_lyrics_tab()` 的滚动 ritual，保留 `switch_to_app()`，tab 选择改为 `self.music_manager.select_tab("lyrics")`
- [x] 1.8 `tests/test_music_adapter_tab_navigation.py`：补 `direction="right"` 与配置预算的上限测试，使该 seam 的测试反映真实调用者
- [x] 1.9 改写 white-box 断言：`tests/test_singer_command.py` 删除 `test_select_singer_tab_scrolls_and_clicks`，改为断言"歌手不可直接播放时命令请求选择 singer tab"；`tests/test_lyrics_command.py` 同样改为断言命令请求选择 lyrics tab
- [x] 1.10 `tests/test_on_demand_old_song_exemption.py` 的 `handler.select_song_tab = lambda: True` 改为补丁 `select_tab`
- [x] 1.11 全量 `uv run pytest -q` 通过；grep 确认无 `select_song_tab` / `select_album_tab` / `select_singer_tab` / `select_playlist_tab` / `select_lyrics_tab` 残留
- [x] 1.12 折叠 lyrics 副本独有的知识：滚动助手用绝对 XPath 在容器内查找，可能返回容器本身。`select_tab` 改为以滚动后重新定位的 tab 为准、助手返回值仅兜底，使五个调用点都获得该保证（并补一条回归测试）

**结果**：`src/` + `config.yaml` 净减 95 行；全量 799 通过（基线 794，新增 5 条 seam 测试）；`select_tab` 从零生产调用者变为五个调用点的唯一实现。

## 2. PlaylistAdoption 深模块 (候选 2 · Strong · in-process)

目标：13 个五连写块 → `guard_switch()` + `adopt()`；`list_mode` 不再是公有可变状态。

- [x] 2.1 定义 `PlaylistAdoption` 接口：`guard_switch(requester) → error?`、`adopt(requester, mode, title, topic, playlist)`；把六个命令文件里的写序固化为实现（状态 → 标题 → 话题）
- [x] 2.2 归一化话题切分：`primary_topic()` 成为「歌曲文案 → 话题」的唯一规则（按 `" - "`，不做裸连字符切分），并在接口文档写明；QQ 音乐电台副标题的裸连字符约定保留为 radio 自己的 `_extract_primary_topic`（两类文本约定不同，混用会解析错）
- [x] 2.3 迁移 `play.py`（`play_favorites` / `play_radar` 两处；`play_song` 是单曲点播，不做房间同步）
- [x] 2.4 迁移 `album.py` / `singer.py` / `playlist.py` / `fav.py`（各 1 / 1 / 1 / 3 处），并把 fav 里重复的筛选关键字→标题映射收敛为 `favourite_filter_title()`
- [x] 2.5 迁移 `radio.py`（5 处）：`_set_room_context` → `_adopt_radio`，写序由模块拥有
- [x] 2.6 `list_mode` 改经 `MusicManager.list_mode` 写入；命令不再直接写在 `QQMusicHandler` 适配器上
- [x] 2.7 新增 `tests/test_playlist_adoption.py`（模块接口级，含纯函数表与写序断言）；`test_playlist_guardian.py` 中三个重复的 "sets player_name" 测试收敛为一个参数化测试
- [x] 2.8 复核 ADR-0004：`InfoManager` 仍为委托 facade，`adopt()` 成为其调用者；测试替身按 ADR-0004 的约定注入到 `PlaylistAdoption`（新增可注入的延迟依赖字段）

**结果**：13 个五连写块归零；`src/` 命令层不再出现任何 `list_mode=` / `player_name=` / `current_playlist_name=` / `set_next_title` / `change_topic`（`:topic` / `:title` 两个专用命令除外，它们不是歌单切换）。815 通过。

**两处有意的行为修正**（记录在提案 Non-Goals 的例外里）：
1. `player_name` 现在只在**切换成功**后写入。原先 album/singer/playlist 在尝试前就写，导致失败的命令也会把房间的「当前播放者」改成请求者，从而替一个并没有播放的人加锁。
2. 电台话题不再做裸 `-` 切分：`_set_room_context` 原来的裸切分对已切分过的文本会二次截断（如 `Lo-Fi 混音` → `Lo`）。

## 3. 聊天 intake 收回 enter/return 横幅文法 (候选 3 · Strong · ports & adapters)

- [x] 3.1 `core/chat_intake.py` 增加 `classify_banner_line()`（新增 `ChatIntakeKind.PARTY_LIKE`）与 `parse_party_like_username()`，吸收 `follower_message.py` 的 enter/return 家族与 点赞 家族
- [x] 3.2 删除 `events/follower_message.py` 的 `_parse_message` 正则副本（含未使用的 `re`/`asyncio`/`Tuple` 导入），事件只保留打招呼点击等 UI 动作
- [x] 3.3 统一 return-vs-enter 语义：横幅与聊天行现在都产出 `USER_RETURN`，「是否算作 return」由 `PresenceTracker` 判定（与 `classify_chat_line` 一致）
- [x] 3.4 把解析表迁到 `tests/test_chat_intake.py::TestClassifyBannerLine`（含 点赞 不被当成进入的回归断言），`test_follower_message.py` 只留 UI 动作与 return 触发

**结果**：818 通过；横幅解析从 12 个内联正则/副本降为 1 个入口。

**遗留发现（未在本候选处理，避免扩大范围）**：`follower_message.handle` 与 `message_content` 里的「`should_trigger_return` → `record_return` → `notify_user_return`」仪式仍是两份（差别只在聊天日志写法）。这是同一个协议的第三份副本，可提为 `PresenceTracker` 上的一个方法；本候选按评审范围只做解析器合并。

## 4. RoomInfoWindow 真模块 (候选 4 · Strong · ports & adapters)

- [x] 4.1 新建 `RoomInfoWindow`：`is_open()` / `ensure_open()` / `ensure_closed()` / `with_window_open()` / `close_with_back()` / `sync_while_open()` / `audit_and_repair()` / `process_pending_retry()`
- [x] 4.2 关闭兜底从 `PartyManager.ensure_room_info_window_closed()` 迁入模块并删除该方法；`topic_manager` 直连 `RecoveryManager.close_drawer` 的那次也改走模块
- [x] 4.3 五处打开 ritual 收敛为一处：`room_name_manager`、`notice_manager`、`topic_manager`、`party_manager`（`room_topic` 分支）、`commands/recommend.py`
- [x] 4.4 `_update_title_ui` 中途对 `RecommendationManager` / `PartyManager` 的伸手改为 `sync_while_open()` —— 「先纠偏（推荐状态/派对类型）再编辑」的顺序现在由模块拥有，审计复用同一步骤
- [x] 4.5 删除 `RoomInfoWindowAuditor`：审计序列并入 `audit_and_repair()`（自带开窗/关窗），`hasattr` 探测随模块消失
- [x] 4.6 新增 `tests/test_room_info_window.py`（17 例：检测/打开兜底/关窗优先序/「只关自己开的那一次」/审计顺序/待重试标记），替换 `test_room_info_auditor.py`；`test_party_manager_room_type_in_room.py` 里重复的两个关窗用例删除

**结果**：831 通过；窗口的打开/检测/关闭/审计各只有一处实现。

**有意保留的边界**（记录理由，便于后续在有真机时收尾）：
- `topic_manager._update_topic_ui` 与 `room_name_manager._update_title_ui` 的**退出**路径没有改走 `with_window_open()`：两者的收尾与紧随其后的 UI 读取/补救纠缠（topic 的「更新过于频繁」要连按三次返回；title 要按返回、回读房名文本、必要时恢复公告）。这些退出序列无法在本机验证，因此只统一了打开与关窗实现，没有改动它们的退出语义。
- `process_pending_retry()` 在生产代码中**没有任何调用点**（原先注释里写的「定时器/循环自动重试」从未接线）。已随模块保留并加注说明，接线与否需单独决定。

## 5. 单一 mic 深模块 (候选 5 · Strong)

- [x] 5.1 `MicManager` 接口定为 `state()` / `set_active(enable, *, report_noop=False)` / `ensure_active()`，并改成依赖可注入（延迟解析 + `_soul_handler`），可进 conftest
- [x] 5.2 折叠三份 content-desc 读取：`playback_muting._mic_state` 删除、`commands/mic.py` 的内联读取删除、`SoulHandler.ensure_mic_active` 删除
- [x] 5.3 「开麦前须先上麦」成为 `set_active(True)` 的强制前置（原先只有 `:mic` 有、`ensure_mic_active` 另有分支、`PlaybackMuting` 完全没有）
- [x] 5.4 `playback_muting`（`state()`/`set_active(False)`/`ensure_active()`）、`:mic`、`:pause` 全部改走模块；`ui_actions.toggle_mic`（盲点击）删除
- [x] 5.5 删除 `MicManager.get_mic_status()`（其 `traceback` 未导入，命中即 NameError）与盲点击的 `toggle_mic()`，本模块成为深模块
- [x] 5.6 测试合并为 `tests/test_mic_manager.py`（含从 `test_soul_handler_seat_take.py` 迁来的三例）；`:mic` 只留「决定目标状态并委托」的测试
- [x] 5.7 更新 ADR-0007：状态注记记录 mic 接缝为 `MicManager`，并把第 1/5 步的 `SoulHandler.mute_mic()/unmute_mic()`（早已不存在的名字）改为实际调用

**结果**：843 通过；`content-desc` 麦克风读取全仓只剩 `mic_manager.py` 一处。

**有意收紧的一处**：`ensure_active()` 在不在麦位时改走 `ensure_on_seat()`（抢麦并等待座位稳定），原先 `SoulHandler.ensure_mic_active` 只调 `grab_mic_and_confirm()` 不等落座。兜底恢复因此可验证「确实坐上麦了」；代价是失败时会多一次等待与一条 error 日志（不再静默）。

## 6. MessageManager 观察接口 (候选 6 · Strong)

- [x] 6.1 定义 `ChatDelta(new_lines, anchor, missed)` 与 `observe(content_list)`：位置 diff、`RECENT_MAXLEN`、锚点兜底全部移入 manager；两个公有 deque 换成私有的 `_recent`
- [x] 6.2 `dispatch(lines, room_owner, from_backfill)` 统一服务实时与补漏：礼物处理、mention 派发、日志分类各只剩一份
- [x] 6.3 `resolve_room_owner()` 改走 `RolePolicy`（ADR-0008），并把 `MessageContentEvent` 里的第二份配置读取与 level-9 回落合并进来
- [x] 6.4 `events/message_content.py` 从 ~270 行收缩到 89 行：拿 `ChatDelta`、派发、按需执行命令或走更新逻辑
- [x] 6.5 聊天流测试改为配置真实的 `MessageManager` 实例（新增 `chat_window` fixture），`monkeypatch MessageManager.instance` 的模式清零

**结果**：845 通过；`recent_chats` / `latest_chats` 与内联 diff 算法在 `src/` 中清零。

**两处有意保留的差异**（由 `from_backfill` 显式表达，而不是各写一份实现）：
1. 回溯发现的命令**入队**交给 runtime 管线执行，实时扫描的命令立即执行（执行时机不同是既有的、有意的设计）。
2. 回溯发现的入场横幅**不**触发「用户返回」（历史行不应重新触发在线事件）。

**修复的一处白盒测试**：`test_missed_detection_fallback_prevents_false_missed` 原先把生产算法抄了一份到测试里验证；现在改为断言 `observe()` 的返回值。

## 7. PendingWrite 内核 (候选 7 · Worth exploring)

- [x] 7.1 新建 `PendingWrite(cooldown_minutes, label)`：`submit` / `has_pending` / `can_apply_now` / `remaining_minutes` / `mark_attempted` / `clear`
- [x] 7.2 `RoomNameManager` 持有该内核，作为 `self._write`：`next_title` / `last_update_time` / `cooldown_minutes` 变成委托属性，`can_update_now` / `get_remaining_cooldown_minutes` / `_advance_cooldown` 委托调用（对外名字不变，遵守 ADR-0001：这是 RoomNameManager 之下的私有内核，不是对房间名不变量的重拆）
- [x] 7.3 `NoticeManager`（15 分钟）与 `TopicManager`（5 分钟）迁移到同一内核；话题那份原先把算术内联在 `get_status()` / `change_topic()` 里，现在也补上 `can_update_now` / `get_remaining_cooldown_minutes`，三个 manager 的冷却接缝因此一致
- [x] 7.4 收敛重复的文本清洗：新增 `helpers/room_banner.py::clean_banner_text()`（房间名 12 字 / 话题 15 字）
- [x] 7.5 顺带收敛客房守卫：`RoomState.in_guest_room()` 取代 13 处逐字重复的 `is_initialized() and ...is_guest_room`
- [x] 7.6 用假时钟为内核写一份测试套件（`tests/test_room_banner_text.py`），并断言三个 manager 的冷却时长与时钟语义

**结果**：863 通过；`last_update_time` 的推进与剩余分钟数各只剩一处实现。

**未处理（记录理由）**：四份命令侧「内部 key → 聊天文案」的映射（`title` / `theme` / `notice` / `topic` 命令的 `update()` 与响应拼装）没有合并：它们的返回文案各不相同、直接面向用户，合并会改变聊天气泡里的原文。这属于「文案规整」而非「计时机制」，与候选 7 的接口不同。

## 8. RuntimeInputPipeline (候选 8 · Worth exploring)

- [ ] 8.1 抽出 `RuntimeInputPipeline.drain()`：console/agent 归一化、queue 文法、静默/私聊路由、meta-commands
- [ ] 8.2 合并 `_detect_initial_room_state` 与 `RoomIdEvent` 为 `verify_current_room()`
- [ ] 8.3 构造函数中的设备 I/O 移入 `DriverLifecycle` 模式
- [ ] 8.4 删除循环内的第二份 queue 文法（`CommandManager:402` 已是唯一 applier）
- [ ] 8.5 让循环体收缩到两次调用，并为 pipeline 补不依赖 `__new__` 的测试
