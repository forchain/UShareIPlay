## 1. 初始化图分析

- [x] 1.1 梳理 `_init_handlers` 内全部初始化项：2 个 handler、25+ 个 manager/state 模块、5 处 controller 接线
- [x] 1.2 确认依赖方向：handlers ← driver/config；managers ← handlers；events ← managers
- [x] 1.3 确认现有测试对 `_init_handlers` 的 monkeypatch 方式（签名须保留）

## 2. 抽取 InitGraph

- [x] 2.1 创建 `src/ushareiplay/core/init_graph.py`：`InitGraph(controller)` + `run()` + 3 个 stage 方法
- [x] 2.2 `init_handlers`：SoulHandler / QQMusicHandler 创建、driver subscriber 注册、logger 赋值
- [x] 2.3 `init_managers`：25+ 单例初始化与 controller 接线原样搬移（含命令解析器初始化）
- [x] 2.4 `init_events`：EventManager 初始化、runtime 配置、事件注册

## 3. AppController 委托与清理

- [x] 3.1 `_init_handlers` 改为委托 `InitGraph(self).run()`，保留异常 log + re-raise 行为
- [x] 3.2 移除 8 个孤儿导入（逐一 grep 确认无其他使用者）

## 4. 测试与验证

- [x] 4.1 新增 `tests/test_init_graph.py`：stage 顺序、stage 独立可调用、controller 委托路径
- [x] 4.2 全量测试 342/342 通过（339 既有 + 3 新增）
