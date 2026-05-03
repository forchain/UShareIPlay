## Tasks

- [ ] 盘点并校准 selector
  - [ ] 确认 `config.yaml` 中 `play_mode_list/play_mode_single/play_mode_random` 是否已对应播放列表界面的 XPath；若不一致则更新或新增 key

- [ ] 引入播放模式缓存（进程内）
  - [ ] 在 `QQMusicHandler` 新增 `play_mode_key`（默认 `unknown`）与中文映射辅助方法/属性

- [ ] 优化 `mode` 命令
  - [ ] 在 recorded!=unknown 且目标一致时短路返回
  - [ ] 在 already_target / 切换成功时写入 `play_mode_key`

- [ ] 播放列表自愈校验
  - [ ] 在 `QQMusicHandler.get_playlist_info()` 进入播放列表界面后识别并修正 `play_mode_key`

- [ ] 扩展 `info` 输出
  - [ ] `InfoCommand` 返回中追加 `play_mode`/`play_mode_key`

- [ ] 最小回归
  - [ ] `python tests/test_imports.py`
  - [ ] `python tests/test_playlist_response_format.py`

