## 1. BaseCommand 迁移到 RoomNameManager

- [x] 1.1 在 `BaseCommand` 中用 `room_name_manager` 惰性属性替换 `theme_manager` / `title_manager` 属性及其实例字段
- [x] 1.2 迁移所有命令调用点（`fav.py`、`album.py`、`play.py`、`playlist.py`、`radio.py`、`singer.py`）到 `self.room_name_manager`
- [x] 1.3 更新命令文件中引用 `title_manager` 的中文注释

## 2. 事件处理器迁移到 RoomNameManager

- [x] 2.1 `events/chat_room_title.py`：`TitleManager.instance()` → `RoomNameManager.instance()`
- [x] 2.2 `events/party_name_violation_later.py`：`TitleManager.instance()` → `RoomNameManager.instance()`

## 3. AppController 移除适配器初始化

- [x] 3.1 从 `AppController._init_handlers` 移除 `ThemeManager.initialize()` 和 `TitleManager.initialize()` 调用及导入，保留 `RoomNameManager.initialize()`

## 4. 删除适配器模块并更新 ADR-0001

- [x] 4.1 删除 `src/ushareiplay/managers/theme_manager.py` 和 `src/ushareiplay/managers/title_manager.py`
- [x] 4.2 更新 `docs/adr/0001-room-name-deep-module.md`：移除保留遗留适配器的理由段落，补充 2026-07 删除记录
- [x] 4.3 迁移测试到 `RoomNameManager`：`test_playlist_playback_warning.py`、`test_radio_old_song_filter.py`、`test_party_name_violation_later.py`、`test_chat_room_title_runtime_context.py`
- [x] 4.4 运行全量测试套件确认 339/339 通过，并 grep 确认无 `ThemeManager` / `TitleManager` 残留引用
