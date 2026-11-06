# Code Review — `feat/unclosable-page-fallback` (main..HEAD)

- Diff: `918522b` — `feat(event): 增加未知页面连续返回失败时的强制关闭 Soul 兜底策略`
- Size: 2 files, **+138 / −20（约 158 changed lines）** — 单次可评审规模
- Scope: `EventManager.react_to_page` 的未知页面兜底链路：新增「初始不在 Soul 前台则禁止 press_back」的防桌面死循环守卫、把原来的非阻塞退避换成「连续 N 次 back 未退出 → `terminate_app` 强制关闭 Soul」、新增 `_is_soul_foreground`，以及对应测试。
- Verdict: **Request changes（R1–R3，其中 R1 必改）**，之后可 approve。方向是对的（危险动作放在 `triggered_count == 0` 且 `ui_busy` 为假之后、阈值可配、日志只在行为触发时打 WARNING），但**新加的守卫恰好把新加的兜底变成了不可达**：只要 back 能把 Soul 送回桌面，计数器每两轮就被清零，`close_app()` 永远不会发生，死循环只是从「每轮一次」降频成「每两轮一次」（见下方 30 轮实测）。

按五轴评审：correctness / readability / architecture / security / performance。安全面无新增输入解析、无凭据、无外部数据；性能只有每轮多解析一次 page_source（R4-P，非阻断）。

---

## R1 — Required: 计数器复位点让 force-close 在「back 能退回桌面」的场景永远不可达，死循环并未消除

`react_to_page` 在分类完初始页面后立刻清零计数器：

```python
# event_manager.py:421-423
is_soul_initial = self._is_soul_foreground(page_source)
if not is_soul_initial:
    self._consecutive_unknown_pages = 0
```

而 force-close 只在 `is_soul_initial` 为真的分支里累加（`event_manager.py:483-499`）。两条路径互斥，于是：

| 场景 | 现状 |
|---|---|
| A. 页面吞掉 back（界面不动，仍在 Soul） | 计数器累加 → 第 10 次 back 时 `close_app()` ✅ |
| B. back 被接受、但把 Soul 退回桌面 | **每两轮计数器归零，`close_app()` 永不触发，`switch_to_app` ↔ `press_back` 无限循环** ❌ |

场景 B 的时间线（主循环 `app_controller.py:734` 每轮 ≈1s + 最多 2.5s 就绪等待）：

```
轮 N   : 初始页面 = Soul 未知页 → 按 back → 桌面。counter=1
轮 N+1 : 初始页面 = 桌面 → counter=0 → switch_to_app → 就绪 → 无事件 → suppressed（不按 back）
轮 N+2 : 初始页面 = Soul 未知页 → 按 back → 桌面。counter=1
...
```

30 轮实测（用生产代码跑，非手推）：

```
round  0 src=Soul    suppressed=None                    counter=1 pressed_back=True  force_closed=False
round  1 src=Launch  suppressed=switched_from_non_soul  counter=0 pressed_back=False force_closed=False
...（每两轮重复一次）
press_back calls: 15   close_app calls: 0   switch_to_app: 30
```

也就是说：**守卫与兜底各自解决了一个场景，但对「back 会退出 App」这个最典型的关不掉场景，两者都没有生效**——commit message 说要防的「返回桌面 -> 切回 -> 返回桌面」死循环仍然在跑，只是频率减半；而为此新加的自愈动作（强制关 App 重进）永远轮不到。同时每轮都会把 Soul 拉回前台再被 back 打回去，冷启动期间也可能被打断。

根因是把「初始不是 Soul」当成「正在加载/正常切回」的**唯一**解释。它其实有两种含义：

1. 界面仍在初始化（本轮不该按 back）—— 守卫正确；
2. **上一轮我们自己按的 back 把 App 送回了桌面** —— 这正是「back 对这个页面无效」的直接证据，应该计入失败次数并升级，而不是清零。

修改建议（最小改动，保持守卫语义，但让证据变成升级信号）：

```python
# __init__ 增加一行状态
self._back_sent_to_background = False   # 上一轮 press_back 之后 Soul 是否被送回后台

# react_to_page 开头
if not is_soul_initial:
    if self._back_sent_to_background:
        # 上一轮自己按的 back 把 Soul 送走了：back 对该页面无效，按失败计数并升级，
        # 但仍不按 back（守卫不变）。
        self._consecutive_unknown_pages += 1
        recovery["suppressed"] = "back_bounced_to_non_soul"
        await self._maybe_force_close(recovery)     # 与 A 场景共用同一处阈值判定
    else:
        self._consecutive_unknown_pages = 0          # 用户/命令主动切走 App，不算失败
        recovery["suppressed"] = None
```

配套要求：

- `press_back` 成功后置 `_back_sent_to_background = True`；**任何事件触发、或连续两轮看到稳定 Soul 页面**时清零，避免把「操作员手动切到桌面」误判成失败（否则一个人拿手机用 10 轮就会被强制关掉 Soul）。
- 阈值判定抽成一处（`_maybe_force_close`），A/B 两条路径共用，避免两份 `>= threshold` + `close_app` 逻辑漂移。
- 必须补一个 B 场景的测试（交替 Soul/桌面 30 轮，断言最终 `close_app()` 被调用、`switch_to_app` 不再无限增长）。现有新增测试全是「初始即 Soul」或「初始即桌面且只有一轮」，覆盖不到这两个分支的组合。

## R2 — Required: 新配置键未落地到 `config.yaml` / `docs/config.md`，且取值未做类型归一化（字符串阈值会静默失效）

```python
# event_manager.py:488-491
threshold = (
    self.config.value("unknown_page_force_close_threshold")
    or self.UNKNOWN_PAGE_FORCE_CLOSE_THRESHOLD
)
```

三个问题：

1. **键不存在**：`config.yaml` 的 `soul` 段没有 `unknown_page_force_close_threshold`，`docs/config.md` 也没有。仓库的既定约定是 `config.yaml` 为唯一基线、`docs/config.md`「只记录 `config.yaml` 里真实存在且生效的键」（见该文首段与顶部 Key 表 `docs/config.md:73`）。现在这个键只活在代码里，运维既不知道它能调，也没有样例，等于半个死配置。参照 `party_restart_minutes`（`config.yaml:42` + `docs/config.md:98`）补一条带注释的默认值（10）。
2. **类型不归一化**：`value()` 原样返回 YAML 值。若写成 `unknown_page_force_close_threshold: "15"`（引号是 YAML 里最常见的失误），`int >= str` 抛 `TypeError`，被外层 `except Exception`（`event_manager.py:501`）以 **debug** 级别记成 `Failed to press back` 后吞掉 → 兜底永久失效，且日志完全看不出原因。实测：

   ```
   threshold='15' -> presses=15 closes=0 counter=15     # TypeError 被吞，计数器无上限增长
   threshold=0    -> presses=15 closes=1 counter=5      # 显式 0 被 `or` 吃掉，静默回落到 10
   threshold=5    -> presses=15 closes=3 counter=0      # 仅 int 正常
   ```

   顺带：`docs/config.md:179` 给出的标准写法就是 `view.soul.value("party_restart_minutes", 720)`，本处用 `or` 绕开了 `default` 参数，既不符合仓库范例，也把 `0` 和 `None` 混为一谈（无法用 0 表达「禁用」）。
3. **无上下界校验**：负数会让 `counter >= threshold` 恒真，第一次未知页就关 App。至少断言 `threshold >= 1`（启动期 fail-fast 或 `max(1, ...)` 都行，选一种并写进注释）。

建议：

```python
DEFAULT_UNKNOWN_PAGE_FORCE_CLOSE_THRESHOLD = 10   # 与 config.yaml 里的默认值一致

def _force_close_threshold(self) -> int:
    value = self.config.value(
        "unknown_page_force_close_threshold",
        DEFAULT_UNKNOWN_PAGE_FORCE_CLOSE_THRESHOLD,
    )
    return int(value)   # 字符串阈值不再静默失败；坏配置当场暴露
```

并补一个 `threshold=3` 的测试断言第 3 次触发关闭，避免以后只剩硬编码默认值被覆盖。

## R3 — Required: 破坏性动作前不复检 `ui_busy` / `paused`，且关闭失败无观测

三处：

1. **窗口期竞态**：`ui_busy` / `paused` 只在 `event_manager.py:449-458` 检查一次，之后还有 `switch_to_app()` + `_wait_page_source_ready_async(max_wait_s=2.5)`（`event_manager.py:463-464`）的 2.5s 等待。这期间命令可以拿到 `ui_session` 锁（`app_controller.py:162`）开始发消息/调座位，操作员也可以 `!stop`。此时 `close_app()` 会**在命令执行中直接杀掉 Soul**，比原来的 `press_back` 后果严重得多（不只是多按一次返回）。请在 `close_app()` 前面复检：

   ```python
   if self.runtime.is_ui_busy() or (self.runtime and hasattr(self.runtime, "is_paused") and self.runtime.is_paused()):
       recovery["suppressed"] = "ui_busy"   # 下一轮再判定，不动 App
   else:
       self.handler.key_actions.close_app()
   ```

2. **`force_closed=True` 是声明而不是观测**：`KeyActions.close_app`（`key_actions.py:42-45`）成功返回 `None`，失败也被 `@with_driver_recovery` 吞成 `None`（`driver_decorator.py:42` 起的 wrapper，三处失败分支都 `return None`），所以「关闭成功」和「terminate 失败」在调用点无法区分。建议让 `close_app` 成功返回 `True` 并在调用点判返回值；不想改 `KeyActions` 就把字段改名成 `force_close_attempted`，不要用既成事实的口吻。

3. **失败完全不可见**：实测把 `close_app` 换成会抛非 `WebDriverException` 的实现，计数器停在阈值不再复位，于是**每轮都重试 terminate，且只留 debug 日志**：

   ```
   round  9 counter=10 force_closed=False close_attempts=1
   round 10 counter=11 force_closed=False close_attempts=2
   round 11 counter=12 force_closed=False close_attempts=3
   ...
   ```

   同时外层 `except Exception as e: self.logger.debug(f"Failed to press back: {e}")` 的文案在 `close_app`/阈值解析抛错时是错的，级别又是 debug。建议把 `close_app()` 单独 `try/except`，失败打 WARNING（破坏性动作失败必须是 WARNING 起步），并考虑 `self.driver_recovery_context.emit("event.force_closed", level="WARNING", ctx={...})`——仓库已经把「driver 恢复」这类关键动作写进 `artifacts/*/events.jsonl`（`observability.py`、`driver_decorator.py` 的 `context.emit`），主动杀 App 更该留一条可复盘的结构化事件。

## R4 — Consider: `_is_soul_foreground` 与 `describe_screen` 是两套前台判定，语义还相反

- `describe_screen`（`event_manager.py:336-346`）：包名集合里**有 Soul 就算 Soul**（优先于 launcher）；
- `_is_soul_foreground`（`event_manager.py:293-303`）：只要**出现任一 launcher 包名就算不是 Soul**；且
  - 无 `package` 属性（`<hierarchy/>`、过渡帧）→ 返回 `True`（fail-open，默认按 Soul 处理，允许 back）；
  - XML 解析失败 → 返回 `False`（fail-closed，抑制 back 且清零计数器）。

同一个 XML，两处结论会不一致；而 `process_current_screen` 在 `react_to_page` 前一行**刚刚**算过 `screen["foreground_app"]`（`event_manager.py:530-531`）就把它丢掉了。所以：

1. 建议收敛成一个 `classify_foreground(page_source_or_root) -> Literal["Soul", "QQMusic", "Launcher", "Unknown"]`，`describe_screen` 与兜底逻辑共用；
2. 「Unknown」要显式决策（过渡帧到底允不允许 back / 是否计入失败），不要用一个 bool 的 `True` 隐含表达；
3. 顺带省掉每轮一次的整份 page_source 解析：`process_current_screen` 可以把已解析的 root（或分类结果）传给 `react_to_page`，否则同一份 XML 每轮解析 4 次（`describe_screen` 1 次、`_is_soul_foreground` 1 次、`_process_events_once` 2 次，外加 `_wait_page_source_ready_async` 每 0.2s 一次的 `_packages_from_page_source`）。当前页面 dump 通常几十万字符，属可感知的 CPU 浪费，但主循环 1s 一轮，不是阻断项。

## R5 — Consider: 兜底分支该抽出来，`recovery` 字典三份重复，`backoff_seconds` 已成死字段

- `react_to_page` 现在 395-507 行（112 行），兜底段嵌套 5 层，把「策略（阈值）」「动作（back/close）」「观测记账（recovery）」混在一处。建议抽 `async def _recover_unknown_page(self, is_soul_initial: bool) -> dict`，把 `_maybe_force_close` 也放进去；守卫和升级都属于同一个策略对象，R1 的修改也只需改一处。
- `recovery` 字典字面量重复 3 份（`event_manager.py:409-419`、`426-433`、`520-528`），每加一个字段必须改 3 处（本次 `force_closed` 就改了 3 处）+ 测试 7 处。抽 `_new_recovery(attempted=False, **overrides)` 可以消掉这类机械同步。
- **`backoff_seconds` 现在恒为 0**：唯一写非零值的地方（旧 `min(10.0, 0.5 * (n-10))` + `await asyncio.sleep(backoff_s)`）已被本次改动删除，但字段仍留在 3 个字典和测试断言里。按 AGENTS「改动引起的孤立引用必须清理」，要么删掉字段（连同测试断言），要么在注释里写明「保留但恒为 0」。目前它是无人读取的假数据（`grep` 只命中定义与测试），会让后来者误以为还有退避机制。

## R6 — Consider: 强制关闭没有冷却/上限，反复自杀式重启只有一条 WARNING

第 10 次 back（约 10–30s，取决于每轮就绪等待）后 `terminate_app` + 下一轮 `switch_to_app` 冷启动。若重启后仍落在同一个关不掉的页面上，这个「10 次 back → 杀 App → 冷启动」会无限循环，每轮只留一条 WARNING，没有任何上限或升级路径；而计数器复位为 0 意味着**系统不记得刚刚关过一次**。

现状里有一个我没看到代码就差点误判为致命的正向设计：冷启动落回首页时 `planet_tab` 事件会触发 `PartyManager.join_party()`（`events/planet_tab.py`），所以常规情况下强制关闭后能自动回房，不是「永久掉线」——这点值得写进 PR 描述，它是这个兜底能成立的前提。但：

- 若重启后仍停在出问题的页面（真正的「特殊关不掉界面」），`planet_tab` 不会触发，就进入上面的循环。建议加「窗口内最多 N 次强制关闭」上限，超限后不再杀 App（避免把可恢复的 UI 卡死升级成无限重启），改为 CRITICAL + 通过 `MessageQueue` 通知操作员，或直接让主循环停下等人处理；
- `close_app()` 后没有任何 settle：下一轮 `get_page_source()` 可能仍拿到旧前台，`_wait_page_source_ready_async` 里 2.5s 对 Soul 冷启动（通常 5–10s）也偏短。至少等页面离开 Soul 前台（或确认 launcher）再继续，避免刚 terminate 就 activate 的竞争。

## R7 — Nits（作者可忽略）

- **N1** 类常量位置：`UNKNOWN_PAGE_FORCE_CLOSE_THRESHOLD`（`event_manager.py:46`）夹在 `__init__` 和 `_PRIORITY_EVENT_KEYS` 之间，按惯例应放到类顶部常量区；它其实是「配置默认值」而非「生效阈值」，叫 `DEFAULT_UNKNOWN_PAGE_FORCE_CLOSE_THRESHOLD` 更准确，若只内部使用可加 `_` 前缀（对齐同文件的 `_PRIORITY_EVENT_KEYS`）。
- **N2** `recovery["suppressed"]` 的取值（`paused` / `ui_busy` / `page_source_not_ready` / 新增 `switched_from_non_soul`）是隐式字符串枚举，无消费者也无 schema。若后续还要加，建议提到模块级 `Literal` 或常量集合，避免拼写漂移；当下不阻断。
- **N3** commit message 只有一行标题。这类兜底改动最需要的是**为什么**：10 是怎么定的、死循环现场长什么样、为什么选择抑制 back 而不是计数（本 review 的 R1 正是从「为什么清零」问出来的）。建议补 commit body 或 PR 描述，并链接触发它的现场记录。
- **N4** 测试夹具 `make_event_manager` 里 `launcher_packages: []`，但生产 `config.yaml` 是 `["com.sec.android.app.launcher"]`；`_launcher_packages()` 又会把 `[]` 与代码默认值合并，所以新测试「能过」的原因和它字面读起来的原因不是同一个。测试里写全（或反过来断言默认值合并）会让 R1 那类语义变化更容易被发现。
- **N5** `describe_screen` 和 `_is_soul_foreground` 每轮各构造一次 launcher 列表（`_launcher_packages()` 里循环 + set），配合 R4 的收敛可一并消掉。

## 测试与验证

| 检查 | 结果 |
|---|---|
| `pytest -q`（全量，venv） | **2721 passed**（127s）。注：本 harness 的 `GIT_CONFIG_COUNT=2` 缺 `GIT_CONFIG_KEY_*`，会让 `git status` 直接 fatal，跑测试前需 `unset GIT_CONFIG_COUNT GIT_CONFIG_VALUE_0 GIT_CONFIG_VALUE_1` |
| 新增/改动测试 | 覆盖了「阈值命中即关 App」「初始桌面 → 抑制 back 且清零」「事件触发 → 清零」，断言了 `pressed_back`/`force_closed`/计数器，无 sleep 依赖 |
| 30 轮交替 Soul/桌面模拟（生产代码） | **15 次 back，0 次 close** → R1 证据 |
| 阈值 = 字符串 `"15"` | **0 次 close**，计数器涨到 15，`TypeError` 被 debug 日志吞掉 → R2 证据 |
| 阈值 = `0` | 静默回落 10（`or` 语义），无法表达「禁用」→ R2 证据 |
| `close_app` 抛异常 | 每轮重试 terminate（5 轮 5 次），计数器不复位、`force_closed=False`、只有 debug 日志 → R3/R6 证据 |
| 运行时/E2E | **未做**：`logs/` 为空，`artifacts/` 只有 pytest 产物，没有一次真机/共享设备运行记录。建议按 `agent-e2e-test` 跑一次手工链路：(a) 制造关不掉的页面，确认第 10 次 back 后 Soul 被 terminate；(b) 冷启动后 `planet_tab` → `join_party` 能回房；(c) 桌面 → 切回时不会误按 back；(d) `!stop`/命令占用 UI 期间不会杀掉 App（R3） |

新增测试里缺的用例（按价值排序）：R1 的「back 退回桌面」循环、R2 的阈值配置与 `threshold - 1` 边界、`_is_soul_foreground` 的单元测试（空包名集合 / 未知包 / QQ 音乐 / Soul+launcher 混排）、关闭失败路径。另外 `test_react_to_page_force_closes_app_on_reaching_consecutive_threshold` 用的是 `<initial />`（无 `package` 属性），它是靠 fail-open 规则（无包名 ⇒ 视为 Soul）才走到关闭分支的，并没有真正测「Soul 前台」；换成带 `cn.soulapp.android` 包名的页面源码，测试才和名字一致。

## Change-shape observations（流程，不是代码）

- 规模很好：2 文件、约 158 行、行为 + 测试同一 commit，评审一轮能读完；分支名 `feat/unclosable-page-fallback` 符合 `<type>/<slug>` 约定。
- 但它仍是**两个独立行为**：①「初始不是 Soul 时抑制 back」（防桌面死循环）②「back 连续失败后杀 App」（自愈）。两者的失败模式不同、可分别回滚，也正因混在一起，R1 里「① 的清零让 ② 不可达」才不容易被看见。下次建议拆两个 commit，第二个基于第一个。
- 没有动 `config.yaml` / `docs/config.md`（R2）。仓库把 `config.yaml` 当唯一基线，新键连默认值都只在 Python 常量里，属于文档漂移的起点。
- 有一处值得保留的克制：危险动作只在 `triggered_count == 0` 且 `ui_busy` 为假时发生，没有顺手重构相邻的恢复链路，符合 Surgical Changes——R3 只是要求把这个判据在执行前**再确认一次**。
