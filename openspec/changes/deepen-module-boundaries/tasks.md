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

- [ ] 2.1 定义 `PlaylistAdoption` 接口：`guard_switch(requester) → error?`、`adopt(mode, title, topic, playlist)`；把六个命令文件里的写序（guard → player_name → list_mode → set_next_title → change_topic）固化为实现
- [ ] 2.2 归一化三种 `topic.split("-")` 规则为一条明确语义，并在接口文档里写明
- [ ] 2.3 迁移 `play.py`（3 处）到 `guard_switch` + `adopt`
- [ ] 2.4 迁移 `album.py` / `singer.py` / `playlist.py` / `fav.py`（各 1 / 1 / 1 / 6 处）
- [ ] 2.5 迁移 `radio.py`（5 处），保留其注释所记录的顺序语义
- [ ] 2.6 `list_mode` 收进 `PlaylistAdoption`/`MusicManager`，移除 `QQMusicHandler` 上的公有可写状态
- [ ] 2.7 用一个接口级测试替换 `test_playlist_guardian.py` / `test_singer_command.py` 里的 mock 链/`side_effect` 脚本
- [ ] 2.8 复核 ADR-0004：`InfoManager` 仍为委托 facade，`adopt()` 成为其调用者

## 3. 聊天 intake 收回 enter/return 横幅文法 (候选 3 · Strong · ports & adapters)

- [ ] 3.1 `core/chat_intake.py` 增加 `classify_banner_line()`，吸收 `follower_message.py` 的 enter/return 家族与 点赞 家族
- [ ] 3.2 删除 `events/follower_message.py:40-68` 的 `_parse_message` 正则副本，事件只保留打招呼点击等 UI 动作
- [ ] 3.3 统一 return-vs-enter 语义（两份副本当前不一致），并补一张纯函数表驱动测试
- [ ] 3.4 迁移 `tests/test_follower_message.py` 到 intake 的纯函数表

## 4. RoomInfoWindow 真模块 (候选 4 · Strong · ports & adapters)

- [ ] 4.1 定义 `RoomInfoWindow`：`with_window_open()` 拥有打开 ritual 与对话框检测，`audit_and_repair()` 拥有审计/修复
- [ ] 4.2 关闭兜底从 `PartyManager.ensure_room_info_window_closed()` 的 `finally` 迁入模块
- [ ] 4.3 四个打开 ritual（`room_name_manager` / `notice_manager` / `topic_manager` / `room_info_auditor`）改为模块调用
- [ ] 4.4 `_update_title_ui` 中途对 `RecommendationManager` / `PartyManager` 的伸手改为模块内的顺序约束
- [ ] 4.5 `room_info_auditor` 的 `hasattr(PartyManager.handler)` 探测改为经模块
- [ ] 4.6 用一份对话框状态 fake 覆盖该 seam，替换现有分散测试

## 5. 单一 mic 深模块 (候选 5 · Strong)

- [ ] 5.1 定义 mic 模块接口：`state()` / `set_active(bool)` / `ensure_active()`
- [ ] 5.2 折叠三份 content-desc 读取（`playback_muting` / `commands/mic.py` / `soul_handler.ensure_mic_active`）
- [ ] 5.3 把"开麦前须先上麦"从注释变为强制不变量
- [ ] 5.4 `playback_muting` / `:mic` / `pause` / `ui_actions` 全部改走新接口
- [ ] 5.5 处理 `MicManager` 的浅模块问题：删除或使其成为新模块的 adapter（其 `get_mic_status` 当前会 NameError）
- [ ] 5.6 合并三份测试为一个行为测试面

## 6. MessageManager 观察接口 (候选 6 · Strong)

- [ ] 6.1 定义 `observe(content_list) → ChatDelta`，把 47 行位置 diff 与 anchor 兜底移入 manager
- [ ] 6.2 `dispatch()` 统一服务 live 与 missed 路径
- [ ] 6.3 房主解析改走 `RolePolicy`
- [ ] 6.4 `events/message_content.py` 收缩为 dispatch 包装
- [ ] 6.5 测试直接注入 manager 依赖，删除 `monkeypatch _instance` 模式

## 7. PendingWrite 内核 (候选 7 · Worth exploring)

- [ ] 7.1 定义参数化 `PendingWrite(cooldown_min, apply)`：`submit` / `due?` / `mark_attempted` / `remaining`
- [ ] 7.2 `RoomNameManager` 改为持有该内核（框架为私有内核，遵守 ADR-0001）
- [ ] 7.3 `NoticeManager` / `TopicManager` 迁移到同一内核，统一"时钟何时推进"语义
- [ ] 7.4 收敛四份命令侧 flush 映射与重复的 `split('|')` 文本清洗
- [ ] 7.5 用假时钟为内核写一份测试套件

## 8. RuntimeInputPipeline (候选 8 · Worth exploring)

- [ ] 8.1 抽出 `RuntimeInputPipeline.drain()`：console/agent 归一化、queue 文法、静默/私聊路由、meta-commands
- [ ] 8.2 合并 `_detect_initial_room_state` 与 `RoomIdEvent` 为 `verify_current_room()`
- [ ] 8.3 构造函数中的设备 I/O 移入 `DriverLifecycle` 模式
- [ ] 8.4 删除循环内的第二份 queue 文法（`CommandManager:402` 已是唯一 applier）
- [ ] 8.5 让循环体收缩到两次调用，并为 pipeline 补不依赖 `__new__` 的测试
