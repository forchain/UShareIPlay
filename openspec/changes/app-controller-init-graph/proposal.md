## Context

架构评审（评级 Speculative）指出：`AppController`（610 行）持有整个初始化图——`_init_handlers` 一个方法内创建 2 个 handler、25+ 个 manager/state 模块，外加多处 controller 接线（`command_manager.controller`、`configure_runtime`、`RuntimeQueueDrainer`、`_status_reporter`）。新增一个 manager 需要理解全部其他 25+ 个的初始化上下文。

评审建议：抽取 `InitGraph` 模块持有顺序与依赖；`AppController` 委托调用；每个 stage 独立可验证。

## Goals / Non-Goals

**Goals:**
- 创建 `src/ushareiplay/core/init_graph.py`：`InitGraph` 持有初始化顺序与依赖
- 按依赖关系划分为 3 个 stage：`init_handlers` → `init_managers` → `init_events`
- `AppController._init_handlers` 委托给 `InitGraph(self).run()`，方法签名不变（现有测试 monkeypatch 此方法）
- 每个 stage 可独立调用、独立测试

**Non-Goals:**
- 不改变任何 manager 的初始化顺序、参数或接线逻辑——纯搬移
- 不引入依赖注入框架或声明式依赖图（投机设计；当前 3 阶段线性顺序已够用）
- 不拆分 `AppController` 的其他职责（监控循环、driver 恢复等）

## Decisions

### 决策 1: InitGraph 持有 controller 引用并直接赋值其属性

**选择**: `InitGraph(controller)`，stage 方法内 `c.soul_handler = ...`、`c.register_driver_subscriber(...)`。

**理由**:
- 初始化代码的本质就是填充 controller 的组成根；让 InitGraph 返回一个"初始化结果"再由 controller 解包会引入无谓的间接层
- `AppController` 属性布局（`self.soul_handler`、`self.info_manager` 等）是对外契约，保持不变

### 决策 2: 三阶段划分跟随既有的依赖方向

**选择**: handlers（依赖 driver/config）→ managers（依赖 handlers）→ events（依赖 managers 就绪）。

**理由**:
- 这就是原 `_init_handlers` 内部的实际执行顺序，划分只是把它显式化
- 命令解析器初始化（`initialize_parser`）依赖 command_manager，归入 managers 阶段尾部，保持原相对顺序

### 决策 3: 阶段内逻辑原样搬移，不做"顺手优化"

**选择**: 逐行搬移，包括日志文案、`RecoveryManager.instance()` 与 `initialize()` 的混用等历史细节。

**理由**:
- 评审评级为 Speculative——先以最小风险建立接缝，行为差异为零
- 任何顺序/接线"修正"都应作为独立变更，便于归因

## Risks & Mitigations

**Risk**: 搬移过程中漏掉某个初始化或改变顺序。
**Mitigation**: 逐行对照原方法；`InitGraph.init_managers` 与原代码 diff 仅为 `self.` → `c.`。全量测试通过。

**Risk**: 孤儿导入——`app_controller.py` 顶部仅为 `_init_handlers` 服务的导入未清理。
**Mitigation**: 逐一 grep 确认后移除 8 个孤儿导入（`SoulHandler`、`QQMusicHandler`、`EventManager`、`NoticeManager`、`PartyManager`、`MessageDispatch`、`PostPartyCreateAutomation`、`RuntimeQueueDrainer`）；保留 `MessageQueue`（监控循环仍在用）。

**Risk**: 现有测试 monkeypatch `_init_handlers` 或依赖其内部行为。
**Mitigation**: 保留 `_init_handlers` 方法签名与异常处理行为（log + re-raise）；`tests/test_app_controller_driver_subscribers.py` 的 monkeypatch 不受影响。

## Testing Decisions

**What makes a good test for this change:**
- `run()` 按依赖顺序调用 3 个 stage（顺序是 InitGraph 的核心职责）
- stage 可独立调用（接缝真实存在，不是又一层伪装）
- `AppController._init_handlers` 确实委托给 InitGraph（防回归：有人把初始化逻辑写回 controller）

**Modules to test:**
- `InitGraph`（新增 `tests/test_init_graph.py`，3 个测试）
- `AppController` 委托路径（同上）

**Prior art:**
- `tests/test_app_controller_driver_subscribers.py` 覆盖 driver subscriber 注册行为（经 monkeypatch `_init_handlers`，不受影响）

## Out of Scope

- manager 之间的隐性依赖声明化（如 `CommandManager` 依赖 `SoulHandler` 就绪）
- `AppController.__init__` 中 driver 初始化的抽离
- `SeatManager.get_instance` 与其他 manager 不同的创建模式统一
