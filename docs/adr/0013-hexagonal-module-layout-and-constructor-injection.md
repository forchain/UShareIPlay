# ADR-0013: 六边形模块布局与构造器注入

## 状态
Accepted

## 背景与问题
现有代码按**技术角色**（`commands/`、`core/`、`dal/`、`events/`、`handlers/`、
`helpers/`、`managers/`、`models/`、`state/`）分目录，而不是按业务能力组织，带来四个
结构性问题（spec #539 的问题陈述）：

1. **领域模型焊死在 ORM 上**：所有持久化模型都继承 Tortoise 模型，DAL 是静态方法
   集合；别名链、Command Level、热度、Playlist Guard、定时器这些规则无法脱离
   SQLite 单独测试。
2. **依赖靠拉取而不是注入**：`Cls.instance()` 遍布 managers / commands / events /
   state / core，读组合根无法还原系统拓扑，单测必须搭台或 patch 多个全局单例。
3. **一个能力散落在最多五个目录**：改一条座位规则要在管理器包、DAO、事件钩子包与
   在线状态跟踪之间来回跳。
4. **外部技术漏进内层**：Tortoise 出现在持久化之外（DB 管理器、定时器管理器），
   Appium / Selenium 被 core、managers、events、handlers 导入，OpenAI SDK 坐在 core。

ADR-0009 §2 把受保护单例契约固定为「业务调用方统一通过 `Cls.instance()` 只读查找」，
§3 又要求删除懒取 Handler 兜底；这两条在本次重构目标下会把依赖关系永久藏在调用点，
因此必须显式取代，而不是默默违反。

## 决策

### 1. 内层与外层：`modules/` 与 `adapters/`
源码分为两个区域：

```
src/ushareiplay/
  modules/                  # 内层：领域模型、用例、端口；按业务能力分组
    shared/ seat/ mic/ playback/ room/ user/ command/ timer/
  adapters/
    inbound/                # chat / ui_events / runtime
    outbound/               # appium(soul, qq_music) / persistence / llm / system
  bootstrap/                # 组合根：装配与运行时循环（最终纵切）
```

`modules/` 内部的包不导入任何具体技术（Appium、Selenium、Tortoise、OpenAI）或
`ushareiplay.adapters`；技术实现只出现在 `adapters/`，由方向朝内的端口连接。
每个内层包的三个单元保持可辨认：`domain.py`（纯数据与规则）、`ports.py`（ABC 端口）、
`use_cases.py`（构造器注入端口的用例）。

### 2. 构造器注入取代受保护单例契约
- `modules/` 内部的一切依赖只从构造器进入；禁止 `Cls.instance()` 查找。
- **取代 ADR-0009 §2（Protected Singleton Contract）**：§2 规定的「业务调用方统一
  通过 `Cls.instance()` 只读查找」在内层不再适用。
- **取代 ADR-0009 §3 的懒处理器措辞**：§3 关于「依赖只从构造函数或
  `configure_runtime` 进入」的目标保留，但「懒取 Handler 兜底」不再作为内层依赖的
  合法来源；内层没有 handler，也不认识 SoulHandler。
- 迁移期间单例可以继续作为**适配器级生命周期装置**存在，并由组合根拥有；
  最终状态是组合根之外没有任何 `.instance()` 查找。
- 端口一律是 `abc.ABC` + `@abstractmethod`，当前实现是异步的保持异步签名。

### 3. 共享内核只放纯代码
`modules/shared/` 收纳：

- `names.py` —— `VisibleName` / `CanonicalName` 值对象（去除首尾空白、大小写敏感，
  两个命名域类型不同、永不相等；见 `docs/users.md`）；
- `roles.py` —— `RolePolicy` 与 `resolve_command_level` / `min_command_level`
  （从 `core/roles.py` 原样迁移，公开名与行为不变）；
- `errors.py` —— `DomainError` 基类；
- `config.py` —— `ConfigView` / `ConfigSectionView` / `ConfigError` 与 `Missing*`，
  纯数据、不导入 AppiumBy；视图仍然**包裹**同一份底层映射，热重载原地生效，错误
  文案逐字不变。元素访问器只返回选择器字符串；
- `ports.py` —— 跨切端口 `RoomMessenger`（公屏发送，遵守 `silent`）、`Clock`
  （`now` + 异步 `sleep`）、`UISession`（`acquire(reason, skip_if_busy)`、
  `holds_session`、`busy_elsewhere`）。

生产实现就地落地，不新包装一层：

| 端口 | 生产实现 |
|---|---|
| `RoomMessenger` | 现有 `MessageDispatch`（在原类上实现端口，发送/静音逻辑不变） |
| `UISession` | 现有 `UISessionLease`（可重入、skip-if-busy、暂停闸门语义不变） |
| `Clock` | 新增 `adapters.outbound.system.clock.SystemClock` |

测试替身放在 `tests/fakes/`（`in_memory_room_messenger.py`、`fake_clock.py`、
`in_memory_ui_session.py`），与既有 `in_memory_*` 约定一致。

### 4. Locator 属于 Appium 适配器（修订 ADR-0012）
ADR-0012 决策 1/2 把 `ConfigView`、`ConfigSectionView` 与 `Locator` 放在同一个
`core/config_view.py`。本次拆分：

- 配置视图迁至 `modules/shared/config.py`，保持纯数据；
- `Locator`（XPath / resource-id 判定、Appium 定位元组、XPath 派生、节点匹配）
  迁至 `adapters/outbound/appium/locator.py`，因为选择器策略是技术细节；
- `ConfigSectionView.element()` / `.maybe_element()` 只返回配置里的选择器字符串，
  需要定位的调用方从 Appium 适配器导入 `Locator` 并自行解释。

ADR-0012 的其余保证（唯一读入口、视图包裹映射、启动期必需元素校验、
`config.local.yaml` 拒绝覆盖元素）全部继续有效。

### 5. 网络桥归入出站系统适配器（修订 ADR-0009 Non-Goal §4）
ADR-0009 的 Non-Goal §4 判定「network_bridge 不迁移」。本 ADR 改判：网络桥属于
外部系统关注点，最终位于 `adapters/outbound/system/`。迁移在最终整合纵切完成，
在那之前旧路径继续工作；不引入双轨兼容层。

### 6. 架构护栏测试
新增 `tests/test_architecture_boundaries.py`：对 `src/ushareiplay/modules/**` 做 AST
扫描，禁止导入 `appium`、`selenium`、`tortoise`、`openai`、`ushareiplay.adapters`，
禁止 `.instance()` 调用。护栏用合成源码验证自身会失败；覆盖范围随每个迁移纵切
扩大，最终覆盖整个 `modules/`。

### 7. 绞杀式迁移，每个纵切删除旧路径
按 spec #539 的迁移序列逐个业务包迁移：领域（纯单测）→ 用例 + 端口（内存替身）→
出站适配器（契约测试）→ 入站适配器变薄 → 组合根装配 → 同一切片删除旧路径。
严禁双轨兼容层；行为（公屏文案、阈值、冷却、时序、DB 结构）逐字不变。

## 与既有 ADR 的关系

| 既有条款 | 处理 |
|---|---|
| ADR-0009 §2 受保护单例契约 | **被本 ADR §2 取代**（内层禁止 `.instance()`） |
| ADR-0009 §3 懒取 Handler 兜底 | **§3 中「依赖只从构造器进入」保留；懒取措辞被本 ADR §2 取代** |
| ADR-0009 Non-Goal §4 网络桥不迁移 | **改判**：网络桥迁至 `adapters/outbound/system/` |
| ADR-0009 Non-Goals §1、§2、§3、§5、§6 | 继续有效（InfoManager 门面、命令不声明式化、runtime_context 不合并、不按覆盖率删测试、不抽多余输入框校验） |
| ADR-0004 InfoManager 门面 | 继续有效；迁入 `room` 包后改为依赖端口而非单例 |
| ADR-0012 Config View / Locator | 语义保留；**位置由本 ADR §4 修订** |
| ADR-0001、0003、0006、0007、0008、0011 | 业务语义不变；模块位置迁移以修订记录登记，不重写原文 |

## 行为等价性说明
1. **公屏与阈值零变更**：本 ADR 及其首个切片（#540）不改变任何公屏文案、阈值、
   冷却或时序；`MessageDispatch` / `UISessionLease` 只是声明实现端口，逻辑原样保留。
2. **配置读取语义不变**：`ConfigView` / `ConfigSectionView` 的取值、异常类型与
   错误文案逐字不变，热重载的对象身份保证不变。
3. **角色与等级不变**：`RolePolicy` 的判定顺序与 `resolve_command_level` /
   `min_command_level` 的匹配规则原样迁移。
4. **测试零放宽**：既有 characterization 断言保持，只有 import 路径与
   「选择器字符串 → `Locator`」的接缝按本 ADR 更新。

## 后果与权衡
- **组合根成为唯一知道具体类的地方**：依赖图从构造器即可读出，但组合根的装配
  代码会变长；这是有意的集中化，最终由 `bootstrap/` 拆小。
- **迁移期存在两种构造形态**：未迁移的旧代码仍可用单例，`modules/` 内及新适配器
  必须构造器注入。护栏测试从不迁移的包开始，防止边界在新代码里先行腐化。
- **`ConfigSectionView` 不再返回 `Locator`**：调用方多一行 `Locator.from_value(...)`，
  换来共享内核零技术依赖；这条迁移在 #540 一次性完成，无兼容层。
- **单例元类改为继承 `ABCMeta`**：为了让现有 `MessageDispatch` 能直接实现端口，
  `SingletonMeta` 继承 `ABCMeta`；单例构造限制与生命周期语义不变。
