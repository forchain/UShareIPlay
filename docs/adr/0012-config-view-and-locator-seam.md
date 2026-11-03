# ADR-0012: 配置视图与 Locator 统一接缝

## 状态
Accepted

## 背景与问题
配置的读取此前散落在八种调用形态里，调用方每次都得自己猜「手上这份映射到底是根配置
（`config.yaml`）还是某个应用段（`soul` / `qq_music`）」，于是出现了多种形状试探：

1. **根/段歧义与形状试探**：`core/ui/element_finder.py` 里的 `config["elements"]` 按段字典
   读；`managers/event_manager.py` 里的 `config.get("soul", {}).get("elements")` 按根字典读；
   `managers/seat_manager/seat_observation.py` 里的 `config.get("elements") or
   config.get("soul", {})...` 两头都试。同一份配置在不同调用点有不同的取法。

2. **静默失效的不变量与死覆盖**：`core/element_wrapper.py` 把**段映射**
   （`soul_handler.config`）当成根映射去探 `config.get("soul")`，该表达式恒为 `None`，
   于是 `config.yaml` 里 `message_reply_view` / `message_reply_content` 的覆盖从未在运行期
   生效 —— 机器人默默用着硬编码兜底的旧选择器，既不报错也不告警。这直接违反 AGENTS.md
   「`config.yaml` 是 UI 元素选择器唯一事实源」的铁律。

3. **XPath 与 resource-id 判定被复述**：判定「一条选择器是 XPath（`//` 开头）还是 Android
   resource-id」这条规则，在 `element_finder`、`event_manager`、`gesture_handler`、
   `seat_panel_driver` 四个模块里各写了一遍；绝对 XPath（`//*`）与相对 XPath（`.//*`）的
   构造口径也在各写各的，DOM 查询因此脆弱。

4. **热重载与字典身份耦合**：`ConfigReloadManager` 为了让热重载生效，要在三个不同的活字典
   上维持原地改写与引用同一性，靠「防引用脱钩」的手工维护兜住，而不是把重载封装在一个
   稳定的门面后面。

5. **文档漂移**：`docs/config.md` 记录了并不存在的顶层 `roles:`、`sleep.start_hour` 与顶层
   `memory:`，反而掩盖了真实结构（`soul.room_owner`、`sleep.start` / `sleep.end`、
   `llm.memory`），把「文档写错」和「配置写错」混成了一团。

ADR-0009 §1 已经要求组合根统一构造与注入，但当时注入的仍是**裸配置字典**，配置读取这一层
始终缺位 —— 缺位的后果就是上面五条。

## 决策

### 1. 唯一读入口：ConfigView / ConfigSectionView
新增 `src/ushareiplay/core/config_view.py`，给出配置读取的唯一入口：
- `ConfigView` —— 根配置的类型化视图：`.soul` / `.music` / `.section(name)` /
  `.maybe_section(name)` / `.value(key, default)` / `.require(key)` / `.command_entries` /
  `.data` / `.reload(...)` / `.validate_required_elements()`。
- `ConfigSectionView` —— 一个应用段的类型化视图：`.element(key)` / `.maybe_element(key)` /
  `.value(key, default)` / `.require(key)` / `.section(key)` / `.maybe_section(key)` /
  `.name` / `.data`。

两个视图都继承自 `object` 而**不是** `dict`：不提供 `view[...]` 下标，也不提供
`view.get(...)`。取值一律走具名方法，让「取的是哪一段」在代码里一眼可见。

### 2. Locator 值对象：判定规则只写一次
`Locator` 是不可变（frozen）值对象，包装一条 UI 选择器：判定 XPath 还是 resource-id、
产出 Appium 定位元组 `(by, value)`、构造绝对 XPath 与相对子节点 XPath、判断一个已解析
XML 节点是不是本选择器指向的元素。四个模块里各写一遍的判定规则从此只有一份
（`Locator.from_value`）。

### 3. 视图包裹底层映射：热重载原地生效
视图**包裹**底层映射而不复制它。`ConfigView.reload(new_mapping)` 原地改写底层根映射，
并把已发出的段视图一并原地更新：根映射、视图实例、段视图实例的对象身份在重载前后都不变，
因此长生命周期的 Handler / Manager 单例不需要重新接线就能看到新配置。
`ConfigReloadManager` 改为经由 `ConfigView.reload` 重载，不再手工维持三份活字典的身份。

### 4. 组合根启动期失败前置校验
`AppController` 在构造时调用 `config.validate_required_elements()`：启动期必需的元素选择器
缺任何一项，当场抛 `MissingElementKey`，机器人起不来，而不是等到运行期操作 UI 时才炸在
一个无关的报错上。必需集合定义在 `core/config_view.py` 的 `REQUIRED_ELEMENTS`。

### 5. config.local.yaml 拒绝覆盖元素定义
`core/config_loader.py` 现在会检查 `config.local.yaml`：出现 `elements`、`risk_elements`、
`drawer_elements`（根级或挂在 `soul.` / `qq_music.` 下）即抛 `LocalConfigOverrideRejected`
（`ValueError` 子类），不做合并。理由是 AGENTS.md 的「元素选择器单一源」铁律 —— 无声的
本地覆盖正是上面第 2 条死覆盖的成因。非元素类的本地覆盖照旧深合并。

### 6. 删除硬编码选择器兜底与死分支
删除 `core/element_wrapper.py` 里探测 `config.get("soul")` 的死分支，以及引用回复、座位面板、
事件检测处的硬编码选择器兜底：选择器要么来自 `config.yaml`，要么不存在。

### 7. 与 ADR-0009 §1 的关系
本 ADR 补齐 ADR-0009 §1 缺失的**配置层**：组合根现在构造 `ConfigView`，并把类型化的段
视图（`config.soul` / `config.music`）注入给 `SoulHandler` / `QQMusicHandler` 与各管理器，
取代裸 dict。ADR-0009 的「构造一次、由组合根注入」原则在配置这条线上第一次真正落地。

## 行为等价性说明
本次改动统一的是**取配置的路径**，不是取到的内容，也不是运行期行为：

1. **选择器不变**：`config.yaml` 里的选择器字符串一条未改；`Locator` 产出的 Appium 定位元组、
   绝对 XPath 与相对 XPath 形态，与各模块此前各自实现的口径逐条对齐（含 resource-id 裸名与
   带包名前缀互相认得的既有语义）。
2. **参数不变**：段内参数、根级参数的读取结果不变，只是改为经 `.value()` / `.require()` 取。
3. **命令表不变**：`commands` 的解析、等级判定与 `sleep.blocked_commands` 的拦截口径不变。
4. **唯一的行为差异是「死覆盖复活」**：`soul.elements` 里 `message_reply_view` /
   `message_reply_content` 的覆盖此前被死分支吞掉、实际用的是硬编码兜底；删除死分支后
   它们第一次真正生效。这是把运行期拉回「`config.yaml` 是唯一事实源」，而不是新增行为。
5. **失败时机前移**：必需选择器缺失从「运行期某个操作报错」变成「启动期报 `MissingElementKey`」。
   报错内容与所指选择器不变，只是发生得更早、更明确。

## 后果与权衡

- **`.data` 逃生舱仍在**：视图保留 `data` 属性供诊断与尚未迁移的调用点读取原始映射。代价是
  这一条路绕过了类型化读取、也绕过了失败前置校验；评审时需要盯住它，不要让它长成第二套
  读配置的惯例。
- **新增异常类型需要处理**：`ConfigError` 之下分 `MissingConfigSection`、`MissingConfigKey`、
  `MissingElementKey` 三支。过去「取不到就回落默认值」的写法现在会抛错 —— `.element()` 与
  `.require()` 是显式失败，`.maybe_element()` 与 `.value(key, default)` 才是可选项。
- **配置写错的代价从「运行期诡异行为」变成「启动失败」**：这是有意的取舍，但代价是改
  `config.yaml` 时若漏掉某个必需选择器，机器人直接起不来 —— 报错信息会指名段名与键名。
- **本地覆盖元素的路子被堵死**：`config.local.yaml` 里再写元素定义会直接被拒。调试时
  「临时换个选择器」不再能靠本地文件绕过，只能改 `config.yaml` 本身并让所有部署同步 ——
  这正是「无声的本地覆盖」这一类问题的根治代价。
- **视图不做缓存**：每次 `.element()` 都回到底层映射取字符串。配置体量下开销可忽略，
  换来的是热重载后无需任何缓存失效逻辑。
