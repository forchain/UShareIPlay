import asyncio
import logging
import queue
import pytest
from unittest.mock import MagicMock

from ushareiplay.core.runtime_services import RuntimeInputPipeline, RuntimeQueueDrainer
from ushareiplay.core.runtime_context import EventRuntimeContext
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.ui.element_finder import ElementFinder
from ushareiplay.managers.event_manager import EventManager
from ushareiplay.models.message_info import MessageInfo


@pytest.mark.asyncio
async def test_stop_command_toggles_start_stop_state():
    """验证新增 Bug 修复：!stop 必须能够切换启停状态（toggle）。

    运行态 -> !stop -> 暂停态 (paused: True)
    暂停态 -> !stop -> 恢复运行 (paused: False)
    """
    input_q = queue.Queue()
    logger = MagicMock()
    timer_mgr = MagicMock()
    timer_mgr.pause = MagicMock()
    timer_mgr.resume = MagicMock()

    pipeline = RuntimeInputPipeline(
        input_queue=input_q,
        room_owner_provider=lambda: "Owner",
        logger=logger,
        send_screen_message=lambda msg: None,
        timer_manager=timer_mgr,
    )

    # 1. 运行态发送 !stop -> 进入暂停态
    input_q.put({"content": "!stop", "source": "console"})
    await pipeline.drain()
    assert pipeline.paused is True
    timer_mgr.pause.assert_called_once()
    assert timer_mgr.resume.call_count == 0

    # 2. 暂停态再次发送 !stop -> 恢复运行态 (toggle)
    input_q.put({"content": "!stop", "source": "console"})
    await pipeline.drain()
    assert pipeline.paused is False
    timer_mgr.resume.assert_called_once()

    # 3. 再次发送 !stop -> 重新进入暂停态
    input_q.put({"content": "!stop", "source": "console"})
    await pipeline.drain()
    assert pipeline.paused is True
    assert timer_mgr.pause.call_count == 2

    # 4. 显式发送 !start -> 恢复运行态
    input_q.put({"content": "!start", "source": "console"})
    await pipeline.drain()
    assert pipeline.paused is False
    assert timer_mgr.resume.call_count == 2


@pytest.mark.asyncio
async def test_stop_command_halts_subsequent_events_in_event_manager():
    """验证验收标准：执行 !stop 后，最多允许出现一个 UI 操作，

    EventManager 在多事件处理循环中遇到暂停状态立即终止，不再执行后续事件。
    """
    executed_events = []

    class FakeController:
        def __init__(self, pipeline):
            self.runtime_input = pipeline

    class FakeModule1:
        class event:
            @staticmethod
            async def handle(key, wrapper):
                executed_events.append("event_1_resolve_natural_language")
                # 模拟在第一个事件执行中/完成时收到 !stop
                pipeline.paused = True
                return None

    class FakeModule2:
        class event:
            @staticmethod
            async def handle(key, wrapper):
                executed_events.append("event_2_party_settings")
                return None

    input_q = queue.Queue()
    pipeline = RuntimeInputPipeline(
        input_queue=input_q,
        room_owner_provider=lambda: "Owner",
        logger=MagicMock(),
        send_screen_message=lambda msg: None,
    )
    controller = FakeController(pipeline)
    runtime_ctx = EventRuntimeContext(ui_lock=asyncio.Lock(), controller=controller)

    handler = MagicMock()
    handler.logger = MagicMock()

    from ushareiplay.core.singleton import Singleton
    Singleton.reset_all_instances()
    em = EventManager.initialize(handler)
    em.configure_runtime(runtime_ctx)
    em.element_to_event = {
        "chat_messages": "msg_mod",
        "party_setting_button": "party_mod",
    }
    em.event_modules = {
        "msg_mod": FakeModule1(),
        "party_mod": FakeModule2(),
    }

    # 模拟从页面源匹配到两个事件
    page_source = "<root><chat_messages/><party_setting_button/></root>"
    em._find_element_in_page_source = lambda root, key, mod: MagicMock()

    triggered = await em._process_events_once(page_source)

    # 验证：事件 1 触发后 !stop 生效，事件 2 被立即终止！
    assert executed_events == ["event_1_resolve_natural_language"]
    assert triggered == 1
    assert "event_2_party_settings" not in executed_events


@pytest.mark.asyncio
async def test_stop_command_halts_element_finder_subsequent_ui_calls():
    """验证验收标准：命令执行多步 UI 操作时，!stop 生效后 ElementFinder 立即拒绝后续调用。"""
    class FakeController:
        def __init__(self, pipeline):
            self.runtime_input = pipeline

    input_q = queue.Queue()
    pipeline = RuntimeInputPipeline(
        input_queue=input_q,
        room_owner_provider=lambda: "Owner",
        logger=MagicMock(),
        send_screen_message=lambda msg: None,
    )
    controller = FakeController(pipeline)

    handler = MagicMock()
    handler.controller = controller
    handler.logger = MagicMock()
    handler.config = MagicMock()
    handler.config.maybe_element = lambda k: MagicMock()

    finder = ElementFinder(handler)

    # 未暂停时，is_interrupted() 为 False
    assert finder.is_interrupted() is False

    # 进入暂停态
    pipeline.paused = True
    assert finder.is_interrupted() is True

    # 暂停态下调用 wait_for_element / wait_for_element_clickable / try_find_element 立即返回 None
    assert finder.wait_for_element("any_key") is None
    assert finder.wait_for_element_clickable("any_key") is None
    assert finder.try_find_element("any_key") is None
    assert finder.wait_for_any_element(["any_key"]) == (None, None)


def test_console_stop_sets_pause_flag_before_the_loop_is_free(monkeypatch):
    """QQ Music 的同步 UI 编排会堵住事件循环，!stop 的标志不能在循环里等。

    控制台线程必须同步落下暂停标志，否则同步 UI 代码下一次查
    `is_interrupted()` 仍看不到暂停，!stop 对 QQ Music 形同虚设。
    """
    from ushareiplay.core.app_controller import AppController

    pipeline = RuntimeInputPipeline(
        input_queue=queue.Queue(),
        room_owner_provider=lambda: "Owner",
        logger=MagicMock(),
        send_screen_message=lambda msg: None,
    )
    controller = AppController.__new__(AppController)
    controller.runtime_input = pipeline
    controller.loop = MagicMock()
    controller.loop.is_running.return_value = True

    deferred = []
    monkeypatch.setattr(
        "ushareiplay.core.app_controller.asyncio.run_coroutine_threadsafe",
        lambda coro, loop: deferred.append(coro),
    )

    assert controller._dispatch_meta_if_needed("!stop") is True
    # 标志立即生效，不依赖事件循环被调度；副作用（定时器/钩子）才延后。
    assert pipeline.paused is True
    assert len(deferred) == 1
    for coro in deferred:
        coro.close()

    # 非启停命令不消费，仍走正常入队路径。
    assert controller._dispatch_meta_if_needed(":play 晴天") is False


@pytest.mark.asyncio
async def test_paused_ui_session_abort_does_not_escape_monitor_loop(monkeypatch):
    """!stop 在事件处理中途触发时，ui_session 抛出的中断信号只能结束本轮处理。

    `CancelledError` 是 BaseException，事件链路里所有 `except Exception` 都接不住；
    若监控循环也不消费它，它就会一路逃出 `asyncio.run`，进程带着 traceback 退出。
    """
    from types import SimpleNamespace
    from ushareiplay.core.app_controller import AppController

    async def _noop(*_args, **_kwargs):
        return None

    controller = AppController.__new__(AppController)
    controller.logger = MagicMock()
    controller.soul_handler = SimpleNamespace(
        error_count=0,
        log_error=lambda *_a, **_kw: None,
        logger=MagicMock(),
    )
    controller.command_manager = SimpleNamespace(load_all_commands=lambda: None)
    controller.timer_manager = SimpleNamespace(
        start=_noop, is_running=lambda: True
    )
    controller.in_console_mode = False
    controller.is_running = True
    controller._drain_agent_command_spool = lambda: None
    controller._runtime_queue_drainer = None
    controller.runtime_input = SimpleNamespace(paused=False, drain=_noop)

    screens = []

    async def process_current_screen():
        screens.append(True)
        if len(screens) == 1:
            # 模拟事件处理途中控制台线程派发 !stop，随后的嵌套 ui_session 被拒。
            controller.runtime_input.paused = True
            raise asyncio.CancelledError(
                "UI session 'state:scrape_online_users' blocked: runtime paused by !stop"
            )
        return {"page_source": "", "screen": {}, "triggered_count": 0}

    controller.event_manager = SimpleNamespace(
        process_current_screen=process_current_screen
    )

    async def fake_sleep(*_args, **_kwargs):
        if controller.runtime_input.paused:
            controller.is_running = False

    monkeypatch.setattr("ushareiplay.core.app_controller.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(
        "ushareiplay.core.app_controller.threading.Thread",
        lambda target: SimpleNamespace(daemon=False, start=lambda: None),
    )
    monkeypatch.setattr(AppController, "_init_handlers", lambda _self: None)
    monkeypatch.setattr(AppController, "_init_runtime_queue", lambda _self: None)
    monkeypatch.setattr(AppController, "_detect_initial_room_state", lambda _self: _noop())
    monkeypatch.setattr(
        "ushareiplay.managers.keyword_manager.KeywordManager.instance",
        lambda: SimpleNamespace(load_keywords_from_config=_noop),
    )

    # 不应抛出：中断信号在监控循环边界被消费，进程进入暂停而非退出。
    await controller.start_monitoring()
    assert screens == [True]


def test_agent_command_spool_dispatches_meta_stop_immediately(tmp_path):
    """后台 spool 管道 (.agent/commands/*.cmd) 必须能即时派发 !stop，

    这样在无交互终端运行（E2E、systemd 等）且 QQ Music 同步操作阻塞事件循环时，
    后台通道注入的 !stop 也能立即生效，而不必留在队列里等到操作结束。
    """
    from ushareiplay.core.runtime_services import AgentCommandSpool

    input_q = queue.Queue()
    dispatched = []

    def fake_dispatch_meta(text: str) -> bool:
        if text.strip() in ("!stop", "stop", "!start", "start"):
            dispatched.append(text.strip())
            return True
        return False

    spool = AgentCommandSpool(
        input_queue=input_q,
        command_dir=tmp_path,
        dispatch_meta=fake_dispatch_meta,
    )

    # 1. 写入普通命令与 !stop
    (tmp_path / "1-cmd.cmd").write_text(":lyrics 晴天\n", encoding="utf-8")
    (tmp_path / "2-stop.cmd").write_text("!stop\n", encoding="utf-8")

    spool.drain()

    # !stop 被 dispatch_meta 拦截消费，未入队
    assert dispatched == ["!stop"]
    assert input_q.qsize() == 1
    item = input_q.get_nowait()
    assert item["content"] == ":lyrics 晴天"


def test_console_prompt_stop_logs_critical_paused(monkeypatch):
    """验证在控制台 Command> 提示符输入 !stop 时，能正常输出 CRITICAL paused 日志，

    不能因为处于输入静音期被 ConsoleLogMuter 过滤掉。
    """
    from ushareiplay.core.app_controller import AppController
    from ushareiplay.core.console_log_muter import ConsoleLogMuter

    muter = ConsoleLogMuter.get_instance()
    muter.unmute()

    logger = logging.getLogger("test_console_prompt_stop")
    logger.setLevel(logging.DEBUG)
    logs = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            logs.append(self.format(record))

    handler = CapturingHandler()
    handler.addFilter(muter)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logger.addHandler(handler)

    pipeline = RuntimeInputPipeline(
        input_queue=queue.Queue(),
        room_owner_provider=lambda: "Owner",
        logger=logger,
        send_screen_message=lambda msg: None,
    )
    controller = AppController.__new__(AppController)
    controller.runtime_input = pipeline
    controller.logger = logger
    controller.is_running = True
    controller.in_console_mode = False
    controller.input_queue = queue.Queue()
    controller.loop = MagicMock()
    controller.loop.is_running.return_value = True

    monkeypatch.setattr(
        "ushareiplay.core.app_controller.asyncio.run_coroutine_threadsafe",
        lambda coro, loop: coro.close(),
    )

    inputs = iter(["", "!stop"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            controller.is_running = False
            return ""

    monkeypatch.setattr("builtins.input", fake_input)
    controller._console_input()

    # 验证日志时序：先记录接收到的控制台命令 !stop，再记录状态切换 paused: True
    assert logs == [
        "CRITICAL:!stop",
        "CRITICAL:paused: True",
    ]

    controller.is_running = True
    inputs = iter(["", "!stop"])
    controller._console_input()
    assert logs == [
        "CRITICAL:!stop",
        "CRITICAL:paused: True",
        "CRITICAL:!stop",
        "CRITICAL:paused: False",
    ]


