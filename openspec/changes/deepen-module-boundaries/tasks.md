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

- [x] 8.1 抽出 `RuntimeInputPipeline.drain()`（`core/runtime_services.py`，与 `RuntimeQueueDrainer` / `AgentCommandSpool` 同一处）：dict/tuple/裸字符串归一化、房主昵称默认、`!stop`/`!timer`/`!dump` 三个 meta 命令、queue 文法路由
- [x] 8.2 合并 `_detect_initial_room_state` 与 `RoomIdEvent` 为 `PartyManager.verify_current_room(room_id, source=...)`（群主转让 / 退房重建 / 记录房间 ID 的唯一判定）
- [x] 8.3 构造函数的设备 I/O 移入 `AppController.start_up()`，由 `__main__` 在 `initialize()` 之后调用 —— `AppController(config)` 现在无副作用
- [x] 8.4 queue 文法只剩一个 applier：新增 `route_queue_text()`，监控循环与 `CommandManager.execute_runtime_queue_messages` 共用
- [x] 8.5 循环体收缩到两次调用（`runtime_input.drain()` + `event_manager.process_current_screen()`）；新增 `tests/test_runtime_input_pipeline.py`（15 例），直接构造管线，不再需要 `AppController.__new__`

**结果**：878 通过；监控循环的输入处理从 ~75 行内联降为一个 `drain()`。

**一处判定收紧**：`route_queue_text()` 采用「只有触发符、没有内容不算命令」的判定（与 `execute_chat_scan` / `process_missed_messages` 一致）。原先循环用的是仅去空白的 `result.text.strip()`，因此裸 `:` 会被当成命令入队；现在会作为普通发言记日志。`CommandManager` 那条路径原先完全不判定，现在同样收紧。

## 9. PR #330 评审跟进（Request changes 的处置）

### 已修（含回归测试）

- **`e0cf184` Critical：`observe()` 提交的是增量而不是窗口。** 静屏时增量是空的，窗口被设成增量就等于被清空 → 下一次观察看不到锚点、整屏被当成新增重新派发（礼物重复道谢、热力值重复写库、命令重复执行）。窗口改为只做追加。回归测试：`test_a_static_screen_is_never_reported_as_new_again`（连观察同屏 4 次不得再报新行）、`test_an_unreadable_screen_does_not_forget_the_window`（屏幕读空也不清窗口）；两条在旧语义下均变红。
- **`e0cf184` Required：补漏去重集缩水。** 旧实现是 `recent_chats ∪ latest_chats`，重构后只剩当前窗口，回溯滚过上一屏的行会被重复派发。新增 `MessageManager._known`（观察前的窗口 ∪ 本次增量），`process_missed_messages` 用它去重。回归测试：`test_process_missed_messages_does_not_re_dispatch_a_previous_screen_line`（旧实现下重复道谢，`2 != 1`）。
  - 未按评审建议把集合放进 `ChatDelta.known`：窗口状态是模块私有（本候选的目标之一就是不让事件解释 manager 的实现细节），去重集是窗口状态的一部分，因此留在模块内。`ChatDelta` 的字段不变。
- **`e0cf184` Required：`RolePolicy` 的默认值短路了库回落。** `RolePolicy.room_owner` 在配置缺省时给出 `DEFAULT_ROOM_OWNER`，用它判断「有没有配」会让 `User.filter(level=9)` 永远走不到。新增 `RolePolicy.configured_room_owner`（没配就是 `None`），`resolve_room_owner` 改读它；`room_owner` 的默认值对其它调用方不变。测试：`test_resolve_room_owner_falls_back_to_the_level_9_user_in_db`。
- **`3a9b0d1` Required：标题刷新路径变成阻塞读。** `_sync_recommendation` 原先无条件 `inspect_current_ui_status(wait=True)`，而旧标题路径用的是非阻塞读；布局里没有 `party_recommendation_status` 时每次改标题都白等满超时。改为 `wait` 参数：被动路径（标题更新）不等待，`audit_and_repair()`（自己刚打开窗口）传 True —— 后者与旧 `room_info_auditor` 的等待语义一致。测试：`test_sync_while_open_corrects_recommendation_status_before_editing` 与 `test_audit_and_repair_...` 各钉一个方向。
- **`2113510` Required：`:mic` 丢掉等待。** 旧 `:mic` 与 `ensure_mic_active` 在读取 content-desc 前会 `wait_for_element_clickable`（默认 10s），重构后 `MicManager.state()` 是即时读，刚就座/刚进房按钮未渲染时立刻报「找不到按钮」；`set_active` 里存活的那个 wait 在读态失败后已提前返回，够不到。`state(*, wait=False)` 加参数：`set_active()` 与裸 `:mic` 传 True（要动手改麦克风就得等），静音保护读态保持非阻塞（旧实现也不等）。测试：`test_set_active_waits_for_the_button_instead_of_failing_fast`、`test_set_active_waits_after_taking_a_seat`、`test_state_reads_without_waiting_unless_asked`。
- **`190c3a7` Required：三个死 import。** `command_manager.py` 的 `expand_queue_text` / `format_manual_message` / `is_manual_operator` 已删除（确认本文件无使用；`runtime_services.py` 与 `say.py` 的真实使用不变）。
- **`190c3a7` Required：pipeline 组装零覆盖。** 新增循环级测试 `test_monitor_loop_assembles_the_runtime_pipeline_and_obeys_pause`：钉住监控循环确实组装了 pipeline、每圈 `drain()`、`paused` 的圈不碰 `process_current_screen()`。
- **`dddc222` Consider：内核 docstring 与话题的 mark 顺序不符。** 内核说「每次尝试之后 mark」，但 `TopicManager.update()` 是**先**推进再调用 —— 保留了原有的分裂语义（UI 调用可能抛出时，先推进才不会因异常跳过整个冷却周期）。docstring 已如实描述两种合法顺序，并写明「别顺手统一」。
- **`190c3a7` Consider：paused 空转。** 暂停分支在 `continue` 前 `await asyncio.sleep(0)`，不再空转烧满一颗核（旧行为原样保留到现在，既然循环级测试已覆盖该分支，顺手修掉）。
- **`dd9f300` Required：横幅解析不再容忍前缀 → 会把前缀当昵称。** 已实测：`classify_banner_line("打个招呼：你关注的Outlier进入房间啦")` 得出昵称 `"打个招呼：你关注的Outlier"`（旧横幅解析用的是非锚定 `re.search`，会正确取到 `Outlier`）；`"任务进度：小红来到了房间"` 得出 `"任务进度：小红"`。两条都会建垃圾 User 行并替它问候。**修法**：通用家族（格式5/6，group 可从行首任意位置起算）的候选名加护栏 —— 含结构标点 `：:，。,.;；` 或超过 24 字即不算昵称；名字紧跟字面量的家族（格式1-4）不加护栏，避免误伤昵称本身含标点的用户。真机横幅不带前缀（已确认），因此不恢复旧的非锚定搜索。测试：`TestClassifyBannerLine` 两条前缀用例 + `test_a_prefixed_banner_yields_no_nickname_at_all`（护栏关闭时三条均变红）。顺带删除 `_ENTER_RETURN_PATTERN`（格式5 的重复副本，已无引用）。

### 记录未修（理由）

- **`e0cf184`：`observe()` 先提交后派发 → 崩溃即丢行。** 旧契约是 at-least-once（旧事件在派发**之后**才 append 窗口），现在窗口在派发前提交。建议的 `commit()` 回调会改变 `ChatDelta` 的形状，本候选的接缝目标是不外露窗口状态；留待单独讨论。
- **`2113510`：`:mic` 报错文案变化（本次核对发现，评审未提）。** 已就座但按钮缺失时，旧代码报 `Microphone button not found`，现在裸 `:mic` 报 `Failed to get mic status`（`state()` 把「按钮不在」和「desc 读不出」都收敛成 None）。当前测试 `test_bare_mic_when_seated_and_status_unreadable_reports_error` 钉的是新文案。判定为文案级差异、不阻塞，但若要恢复旧文案，需要让 `MicManager` 暴露「读不到状态时的文案」而不是在命令里探元素。
- **`2113510`：`set_active` 读态→点击之间 TOCTOU 变宽；裸 `:mic` 读两次状态非原子。** 既有并发面，非本次引入。
- **`dd9f300`：`slide_drawer` 折叠态若仍在层级里，`ensure_open` 的 `is_open()` 探测会误判「已开」。** 需真机验证（`DIALOG_KEYS` 命中任一项即算开着）。
- **`833eb1e`：album 话题名过 `primary_topic()` 会被 `" - "` 截断**（专辑名含 `" - "` 即出错）；**`adopt()` 标题失败现在抑制话题写入**，而 5 个原调用点里有 4 个不是这个语义。两处均为行为发散，未定案。
- **`dddc222`：mark 顺序差异未加钉住测试。** 两处 UI 调用都把异常收敛成 error dict，因此「先 mark / 后 mark」在当前代码里不可观测 —— 加测试等于钉一个不可达路径。docstring 已写明差异与理由；若将来真的要让 UI 调用直接抛异常，届时必须同时补测试。
