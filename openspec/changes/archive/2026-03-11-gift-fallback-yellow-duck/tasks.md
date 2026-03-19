## 1. 核心逻辑实现

- [x] 1.1 在 `src/managers/user_manager.py` 的 `send_gift()` 中，读取 `luck_item.text` 后增加"小黄鸭"判断分支
- [x] 1.2 小黄鸭分支：调用 `click_element_at(luck_item)` 点击礼物本身，不点击 `give_gift`/`use_item`
- [x] 1.3 小黄鸭分支：调用 `_close_online_drawer()` 并返回 `{'success': '小黄鸭 送你啦'}`

## 2. 验证与测试

- [x] 2.1 在背包为空的状态下执行 `:gift <用户名>`，确认小黄鸭被点击且界面正常返回在线列表
- [x] 2.2 在背包有礼物的状态下执行 `:gift <用户名>`，确认原有赠送流程不受影响
- [x] 2.3 确认 `gift` 命令成功时聊天区显示正确的成功消息
