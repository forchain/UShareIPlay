## Tasks

- [x] 盘点并校准 selector
  - [x] 确认 `config.yaml` 中 `play_mode_list/play_mode_single/play_mode_random` 是否已对应播放列表界面的 XPath；若不一致则更新或新增 key

- [x] 引入播放模式缓存（进程内）
  - [x] 在 `QQMusicHandler` 新增 `play_mode_key`（默认 `unknown`）与中文映射辅助方法/属性

- [x] 优化 `mode` 命令
  - [x] 在 recorded!=unknown 且目标一致时短路返回
  - [x] 在 already_target / 切换成功时写入 `play_mode_key`

- [x] 播放列表自愈校验
  - [x] 在 `QQMusicHandler.get_playlist_info()` 进入播放列表界面后识别并修正 `play_mode_key`

- [x] 扩展 `info` 输出
  - [x] `InfoCommand` 返回中追加 `play_mode`/`play_mode_key`

- [x] 最小回归
  - [x] `python tests/test_imports.py`
  - [x] `python tests/test_playlist_response_format.py`

