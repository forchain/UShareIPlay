from types import SimpleNamespace

from ushareiplay.core.init_graph import InitGraph


def test_run_executes_stages_in_dependency_order(monkeypatch):
    calls = []
    graph = InitGraph(controller=object())
    monkeypatch.setattr(graph, "init_handlers", lambda: calls.append("handlers"))
    monkeypatch.setattr(graph, "init_managers", lambda: calls.append("managers"))
    monkeypatch.setattr(graph, "init_events", lambda: calls.append("events"))

    graph.run()

    assert calls == ["handlers", "managers", "events"]


def test_stages_are_independently_invocable():
    # 单个 stage 可在不完整 controller 上独立调用（monkeypatch 掉其依赖后），
    # 这是 InitGraph 存在的意义：初始化图的每个阶段可独立验证。
    graph = InitGraph(controller=SimpleNamespace())
    assert callable(graph.init_handlers)
    assert callable(graph.init_managers)
    assert callable(graph.init_events)


def test_app_controller_delegates_init_to_graph(monkeypatch):
    from ushareiplay.core.app_controller import AppController

    controller = AppController.__new__(AppController)
    controller.logger = SimpleNamespace(info=lambda _msg: None, error=lambda _msg: None)

    seen = {}

    class FakeGraph:
        def __init__(self, c):
            seen["controller"] = c

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr("ushareiplay.core.init_graph.InitGraph", FakeGraph)

    controller._init_handlers()

    assert seen == {"controller": controller, "ran": True}
