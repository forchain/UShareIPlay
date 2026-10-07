# ADR-0009: Composition Root 依赖注入与受保护单例契约

## 状态
Accepted

## 背景与问题
在重构前，UShareIPlay 的多个子系统（`managers/`、`state/`、`events/`、`commands/`）广泛存在函数体内延迟导入并调用 `SoulHandler.instance()` 或直接读取全局单例的模式（基线全仓函数体内 import 高达 228 处）。
这种设计虽然绕开了模块间的循环依赖与启动时序问题，但也带来了明显的架构缺陷：
1. 依赖关系隐藏在深层业务逻辑或属性访问器中，阅读 Composition Root 无法还原完整的系统拓扑图。
2. 单元测试难以进行干净的轻量化搭台，往往需要 mock 多个全局单例才能实例化一个基础服务。
3. 麦位子系统多个服务（`SeatManager`、`SeatUIManager`、`SeatCheckManager`、`ReservationManager`、`SeatingManager`、`SeatObservationManager`）单例职责与构造契约未完全统一。

## 决策

### 1. Composition Root 统一构造与注入
所有长生命周期的核心服务均由组合根 `AppController` 在启动时通过 `initialize(handler=self.soul_handler, ...)` 显式实例化并完成依赖注入。所有服务类均在 `__init__` 中接受显式依赖，默认值允许测试或解耦时传 `None`。

### 2. 受保护单例契约（Protected Singleton Contract）
所有受保护的系统级服务统一继承 `Singleton`（元类为 `SingletonMeta`）：
- 严禁通过类的直接构造函数 `Cls()` 创建实例，违者抛出明确的 `SingletonError("Use Cls.initialize(...) to create singleton instances")`。
- 全系统 35 个单例类均受此契约约束并通过自动化测试覆盖。
- 业务调用方统一通过 `Cls.instance()` 进行只读查找；严禁在组合根以外的地方重新初始化。

### 3. 彻底删除全部懒取 Handler 兜底
- 全仓彻底删除 `from ushareiplay.handlers.soul_handler import SoulHandler; self.handler = SoulHandler.instance()`。
- 全仓 `src/` 内 `SoulHandler.instance()` 调用点降为 0（仅在 `AppController` 顶层调用 `SoulHandler.initialize(...)`）。
- 依赖只从构造函数或 `configure_runtime` 进入。
- 服务内部的 `logger` 统一由注入的 `handler.logger` 提供，无 handler 时安全回退至模块同名 `logging.getLogger(...)`。

### 4. 懒加载严格限定于真循环依赖
- 严禁在无循环引用的代码中随意使用函数体内 `import`。
- 逐一排查后确需保留延迟加载的位置，必须在其属性或方法的 docstring 中显式注明循环引用的另一端是谁（例如 `RoomInfoWindow` 与各业务 Manager 互引、`InfoManager` 与 `PartyManager` 顶层互引、`PresenceTracker` 与 `CommandManager` 的跨层交互）。
- 本次重构后，`src/` 内函数体内 import 数量从基线 228 处大幅减少至 155 处（净减少 73 处，降幅逾 32%）。

### 5. 运行时重新绑定（bind_handler）的裁决
对 `bind_handler` 接口进行收敛与语义澄清：
- 仅保留应对驱动崩溃重启或轻量上下文切换时的必要更新（`MessageDispatch.bind_handler` 更新底层发送通道，`SeatObservationManager.bind_handler` 同步更新观测器及其 UI 委派）。
- 每个保留的方法均显式注明其绑定的实体与理由。

## 行为等价性说明（Behavioral Equivalence）
本次全流程重构（#359 系列 ticket #360 至 #368）保持了严格的行为等价性：
1. **测试断言零放宽**：除个别座位测试搭台代码从 `SeatManager()` 修正为符合单例契约的 `SeatManager.initialize(...)` 之外，既有业务逻辑断言零修改，无任何一条断言是为了掩盖行为变更而调整。
2. **麦位策略零变更**：抢麦规则、他人房间客房守卫判定（`RoomState.in_guest_room()` / `@guest_room_guard`）、麦位重扫阈值（2）与冷却时间默认值（60s）严格保持不变。
3. **公屏交互零变更**：所有公屏广播文案、静音生命周期（`PlaybackMuting`）与事件互斥语义保持 100% 一致。
4. **测试结果**：全量测试套件 1151 tests passed。

## 判定不做且不再重复提案的条目（Non-Goals / Excluded Proposals）
为避免后续代理或代码审查被旧的泛化重构建议带偏，特此固定判定不做以下提案：
1. **解散 InfoManager 门面**：ADR-0004 已明确拒绝解散方案，保持其作为 5 个状态模块的聚合门面。
2. **命令声明式化**：当前命令解析器（`CommandParser`）与各命令模块解耦良好，过度声明式抽象会增加不必要的元编程开销。
3. **runtime_context 合并**：命令运行期上下文与主控制器生命周期职责独立，强行合并将破坏关注点分离。
4. **network_bridge 迁移**：网络桥接代码边界清晰，在当前包路径下运行稳定，搬家无实际收益且破坏历史可追溯性。
5. **按所谓覆盖率删测试**：坚决保留各层次防御性单测与边界测试，杜绝以精简为名的削弱防护网行为。
6. **抽出多余的输入框校验方法**：当前输入已由纯函数 `chat_intake` 统一分类和规范化，不需要再抽中间层。

## 修订记录（Amendments）

### 2026-10-07 —— 第 21 行的「35 个单例类」已不是当前盘点结果

第 11 行的问题陈述与第 21 行的计数记录的是 #359 系列**当时**的决定，属于历史结论，
**不回改**；此处只登记当前值，以免后续审查再拿它当现状引用。

按同一口径重数（`Singleton` 的具体实现类；不含抽象基类 `SeatManagerBase`；不含由
组合根直接构造并注入的两个 handler 单例 `SoulHandler` / `QQMusicHandler`，因为它们
本来就由第 1 条的「构造一次、由组合根注入」覆盖）：

| 时点 | 具体单例类 | 扣掉两个 handler 单例 |
|---|---|---|
| 本 ADR 引入时（`95a219a`，2026-10-01） | 37 | **35** ← 第 21 行的来源 |
| 今日 | 33 | **31** |

差额的来龙去脉：#395 / #400 / #401 删掉了四个座位内部单例（`SeatUIManager`、
`SeatCheckManager`、`ReservationManager`、`SeatingManager`），同期没有新增任何单例，
35 → 31。新增的 `SeatSubsystem` 与 `SeatPanelDriver` **刻意不是单例**（前者由组合根
构造并持有一个实例，后者是无全局状态的普通可注入对象），所以它们不进这个数 —— 这是
本契约想要的形态，不是缺口。
