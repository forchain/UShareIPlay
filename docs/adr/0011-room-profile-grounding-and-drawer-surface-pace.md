# ADR-0011: 房间档案必须从 UI 接地；抽屉是一块限速表面

## 状态
Accepted（2026-10）

## 背景与问题

`RoomProfileManager` 拥有三个字段（话题 5 分钟 / 公告 15 分钟 / 房名 10 分钟），
每个字段一份 `PendingWrite` 预算，互不消耗（ADR-0001）。运行日志暴露出两个由
「预算各记各的」派生的缺陷：

1. **档案从未被接地**：`current_title` 只有三个写入口（`initialize_from_ui`、
   `_parse_title_from_ui`、以及 `_write_title_in_drawer` **写成功**的那一刻）。
   PR #413 停用抽屉里的推荐读写时，把 `PartyManager._refresh_recommendation_state()`
   做成了空壳 `return None` —— 而它原本是 `RoomProfileManager.ensure_synced_on_return()`
   唯一的生产调用点，往下正是 `initialize_from_ui`。此后房名与主题再也读不回真实值：
   `:theme` 只能报「当前标题: 未设置」，房名写入一旦被 Soul 拒绝就连兜底都没有。
   `get_title_to_update()` 那条「没初始化就去 UI 读一次」的兜底又被排队中的草稿饿死。

2. **承诺了一个服务端会拒绝的「soon」**：`set_title` 只看房名自己的 10 分钟预算，
   于是 19:30:27 敢说 `will be updated soon`；可 19:30:38 话题刚在同一块抽屉里写成功，
   19:30:44 的房名提交就被判「改得太频繁」。被拒一次仍然 `mark_attempted`，代价是
   一整个房名周期（10 分钟静默）——一次本可避免的碰撞换来 10 分钟的沉默。

## 决策

### 1. 接地是生产契约，不是可选项
- 回房 / 进房 / 建房三条生命周期路径必须调用 `ensure_synced_on_return()`，把真实房名
  （`{theme}｜{title}`）读回来一次。
- `:title` 的心跳 `update()` 也调它作为兜底：进程重启时机器人可能已经坐在房里，
  `join_party` 一条都不会走。
- **接地是只读的**：`initialize_from_ui` 优先读抽屉里那一行，抽屉没开时回落到主界面
  `chat_room_title` 的文本 —— 一个点击都不发生，因此不违反 #413「不再为了推荐开抽屉」。
- 读不到就不假装成功：保持未初始化，最坏每 `GROUNDING_RETRY_SECONDS`（60 秒）重试一次，
  避免每拍给监控循环白加两秒的元素等待。
- 守卫问的是**本模块知不知道**（`is_initialized`），不是已废弃的推荐字段记没记过。
- 房间标识一变（`RoomState.room_id` setter 与 `clear()`）就 `invalidate_ui_state()`：
  上一间房读回来的房名/主题作废，退避计时器同时清零。**冷却预算与排队草稿不动**。

### 2. 字段预算与抽屉表面是两个问题，分开答
`ProfileDraftStore` 现在提供两个查询：
- `can_apply_now(field)`：字段**自己**的 5/15/10 分钟到了没。**保持原语义**，
  抽屉会话**内部**的连带动作（房名写入顺手把被冲掉的公告当场补回去，用户故事 #6）
  走这一条 —— 它不开新的写入会话，不该被表面节奏拦去排队。
- `can_start_write(field)`：能不能**开始**一次该字段的抽屉写入 = 字段预算 **且**
  距任何一个字段上次真实写入已满 `SURFACE_SPACING_SECONDS`（60 秒）。心跳的三个
  flush（`update_topic` / `update_notice` / `update_title`）与三个 setter 的 ETA
  分支都改问这一条。
- `minutes_until_write(field)`：对外报的「还要等多久」= 两者里更晚的那个；字段预算
  那一半沿用 `int()` 向下截断（ADR-0009 的等价性要求），表面那一半向上取整，
  因为 0 会被读成「马上就能写」，而那正是撞一次被拒的起点。

被表面节奏闸挡住时**不记账**（不 `mark_attempted`）：一次点击都没发生，草稿与预算
都留着，下一拍再写 —— 与既有「没写成就别记账」的原则同形。

## 后果

- `:theme` / `:title` 不再报「当前标题: 未设置」，也不再承诺一个会被拒的「soon」；
  字段各记一份预算这一 ADR-0001 的核心不变量没有被削弱，只是多了一层表面节奏。
- 同一拍里排队的房名与话题会相差约 60 秒落地（相对 5/10/15 分钟的字段预算是零头），
  换来的是少一次被拒与少一整个周期的静默。
- 60 秒是对 Soul 侧「房间信息面板编辑频率」的保守估计。若将来观察到更长的服务端窗口，
  只需调 `SURFACE_SPACING_SECONDS` 一处；不要退回「每个字段各猜各的」。
- `audit_and_repair()` 与 `process_pending_retry()` 至今仍无生产调用点：公告纠偏与
  派对类型纠偏本来就跑在每一次抽屉写入会话里（`sync_while_open`）。若将来要让它们
  重新上岗，接的应当是**心跳层**，并且不得再把接地当成推荐的附属品。
