"""运行时主循环：监控轮询、控制台/agent 输入管线、队列消费、状态快照与关停。

从原 AppController 拆出，与组合根（`bootstrap.container`）分离：
本模块不直接导入任何出站具体适配器，全部协作者由组合根构造并注入。
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, Tuple, Type

from ushareiplay.adapters.inbound.runtime.runtime_services import (
    AgentCommandSpool,
    RuntimeInputPipeline,
    RuntimeQueueDrainer,
    StatusReporter,
)
from ushareiplay.core.console_log_muter import ConsoleLogMuter
from ushareiplay.modules.shared.roles import RolePolicy


class RuntimeLoop:
    """运行期监控与输入派发循环。"""

    def __init__(
        self,
        *,
        config,
        obs,
        lease,
        room_owner_provider: Callable[[], str],
        agent_command_dir: Optional[Path] = None,
        driver_provider: Optional[Callable[[], Any]] = None,
        stale_element_exceptions: Tuple[Type[BaseException], ...] = (),
        driver_exceptions: Tuple[Type[BaseException], ...] = (),
    ):
        self.config = config
        self.obs = obs
        self.lease = lease
        self._room_owner_provider = room_owner_provider
        self._driver_provider = driver_provider or (lambda: None)
        self._stale_element_exceptions = stale_element_exceptions
        self._driver_exceptions = driver_exceptions

        self.input_queue: queue.Queue = queue.Queue()
        self.agent_command_dir = agent_command_dir or (Path(".agent") / "commands")
        self.is_running = True
        self.in_console_mode = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._non_ui_task: Optional[asyncio.Task] = None

        self.runtime_input: Optional[RuntimeInputPipeline] = None
        self.runtime_queue_drainer: Optional[RuntimeQueueDrainer] = None
        self.agent_command_spool = AgentCommandSpool(
            input_queue=self.input_queue,
            command_dir=self.agent_command_dir,
            obs=self.obs,
            config=self.config,
            dispatch_meta=self._dispatch_meta_if_needed,
        )
        self.status_reporter = StatusReporter(
            config=self.config,
            lease=self.lease,
            obs=self.obs,
        )

        # 运行期依赖由组合根通过 bind_services 注入
        self.logger: Any = None
        self.soul_handler: Any = None
        self.command_manager: Any = None
        self.event_manager: Any = None
        self.timer_manager: Any = None
        self.user_memory: Any = None
        self.keyword_use_cases: Any = None
        self.party_service: Any = None
        self.message_dispatch: Any = None
        self.message_queue: Any = None
        self.config_reload_manager: Any = None
        self.post_party_create_automation: Any = None

    def bind_services(
        self,
        *,
        logger,
        soul_handler,
        command_manager,
        event_manager,
        timer_manager,
        user_memory,
        keyword_use_cases,
        party_service,
        message_dispatch,
        message_queue,
        config_reload_manager,
        post_party_create_automation,
    ) -> None:
        self.logger = logger
        self.soul_handler = soul_handler
        self.command_manager = command_manager
        self.event_manager = event_manager
        self.timer_manager = timer_manager
        self.user_memory = user_memory
        self.keyword_use_cases = keyword_use_cases
        self.party_service = party_service
        self.message_dispatch = message_dispatch
        self.message_queue = message_queue
        self.config_reload_manager = config_reload_manager
        self.post_party_create_automation = post_party_create_automation

        self.status_reporter.soul_handler = soul_handler
        self.status_reporter.timer_manager = timer_manager
        self.status_reporter.message_queue = message_queue

    def _toggle_console_mode(self) -> None:
        """Toggle console mode on Ctrl+P"""
        if not self.in_console_mode:
            self.logger.info("Entering console mode. Press Ctrl+P again to exit...")
            self.in_console_mode = True
        else:
            self.logger.info("Exiting console mode...")
            self.in_console_mode = False

    def _dispatch_meta_if_needed(self, text: str) -> bool:
        """控制台线程入口：立即切换暂停标志，定时器/中断钩子留给事件循环。"""
        if not self.runtime_input:
            return False
        loop = self.loop
        if not (loop and loop.is_running()):
            return False
        paused = self.runtime_input.toggle_paused(text.strip())
        if paused is None:
            return False
        asyncio.run_coroutine_threadsafe(
            self.runtime_input.apply_pause_side_effects(paused), loop
        )
        return True

    def _console_input(self) -> None:
        """Background thread for console input"""
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(errors="replace")
            except Exception:
                pass

        muter = ConsoleLogMuter.get_instance()

        while self.is_running:
            try:
                if self.in_console_mode:
                    user_input = input("Console> ")
                    if user_input.strip():
                        if self.logger:
                            self.logger.critical(f"{user_input}")
                        if not self._dispatch_meta_if_needed(user_input):
                            self.input_queue.put((user_input, "console"))
                else:
                    user_input = input("")
                    if not user_input.strip():
                        muter.mute()
                        try:
                            command = input("Command> ")
                        finally:
                            muter.unmute()
                        if command.strip():
                            if self.logger:
                                self.logger.critical(f"{command}")
                            if not self._dispatch_meta_if_needed(command):
                                self.input_queue.put((command, "console"))
                    else:
                        if self.logger:
                            self.logger.critical(f"{user_input}")
                        if not self._dispatch_meta_if_needed(user_input):
                            self.input_queue.put((user_input, "console"))
            except UnicodeDecodeError as e:
                muter.unmute()
                if self.logger:
                    self.logger.warning(f"Console input decode error: {e}")
                continue
            except EOFError:
                break
            except KeyboardInterrupt:
                muter.unmute()
                if self.in_console_mode:
                    self.in_console_mode = False
                    if self.logger:
                        self.logger.info("Exiting console mode...")
                else:
                    self.is_running = False
                break
            except Exception as e:
                muter.unmute()
                if self.logger:
                    self.logger.error(f"Console input error: {e}")
                time.sleep(0.5)
                continue

    def _drain_agent_command_spool(self) -> None:
        self.agent_command_spool.drain()

    def _spool_input_loop(self) -> None:
        """Background thread for agent command spool."""
        while self.is_running:
            try:
                self._drain_agent_command_spool()
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Spool input error: {e}")
            time.sleep(0.05)

    async def _detect_initial_room_state(self) -> None:
        """启动时：找到房间 ID 并交给 PartyService 核对（与运行期同一判定）。"""
        try:
            if not self.soul_handler or not hasattr(self.soul_handler, "element_finder"):
                return
            room_id_elem = self.soul_handler.element_finder.try_find_element("room_id", log=False)
            if not room_id_elem:
                return
            room_id_text = self.soul_handler.element_finder.get_element_text(room_id_elem)
            if not room_id_text or not isinstance(room_id_text, str):
                return

            await self.party_service.verify_current_room(
                room_id_text.strip(), source="startup"
            )
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Initial room detection skipped: {e}")

    def init_runtime_queue(self) -> None:
        """构造运行时输入管线与队列 drainer，并注册 !stop 中断钩子。"""
        send_screen = (
            (lambda text: self.message_dispatch.send_screen_message(text))
            if self.message_dispatch is not None
            else (lambda _text: None)
        )
        reload_fn = (
            (lambda: self.config_reload_manager.reload().render())
            if self.config_reload_manager is not None
            else None
        )
        self.runtime_input = RuntimeInputPipeline(
            input_queue=self.input_queue,
            room_owner_provider=self._room_owner_provider,
            logger=self.logger,
            send_screen_message=send_screen,
            message_queue=self.message_queue,
            timer_manager=self.timer_manager,
            obs=self.obs,
            dump_artifacts=self._dump_readonly_artifacts,
            reload_config=reload_fn,
            is_admin=lambda name: RolePolicy(self.config).is_admin(name),
        )
        self.runtime_queue_drainer = RuntimeQueueDrainer(
            handler=self.soul_handler,
            command_manager=self.command_manager,
            send_screen_message=send_screen,
            message_queue=self.message_queue,
            obs=self.obs,
            logger=self.logger,
            runtime_input=self.runtime_input,
            drain_agent_spool=self._drain_agent_command_spool,
        )
        self.runtime_input.register_interruption_hook(
            self.runtime_queue_drainer.cancel_active_command
        )

    async def _dump_readonly_artifacts(self, reason: str = "") -> None:
        paths = self.obs.paths()
        driver = self._driver_provider()
        try:
            src = driver.page_source
            paths.page_source_xml.write_text(src or "", encoding="utf-8")
            self.obs.emit("artifact.page_source", ctx={"path": str(paths.page_source_xml), "reason": reason})
        except Exception:
            self.obs.emit("artifact.page_source.error", level="ERROR", ctx={"reason": reason, "error": traceback.format_exc()})
        try:
            ok = driver.get_screenshot_as_file(str(paths.screenshot_png))
            self.obs.emit("artifact.screenshot", ctx={"path": str(paths.screenshot_png), "ok": bool(ok), "reason": reason})
        except Exception:
            self.obs.emit("artifact.screenshot.error", level="ERROR", ctx={"reason": reason, "error": traceback.format_exc()})

    async def _update_status_from_screen(self, screen: dict) -> None:
        await self.status_reporter.update(
            screen=screen,
            automation=self.post_party_create_automation,
        )

    async def start_monitoring(self):
        error_count = 0

        self.logger.info("加载命令模块...")
        self.command_manager.load_all_commands()
        self.logger.info("All command modules loaded")
        self.logger.info("命令模块加载完成")

        self.logger.info("初始化关键字系统...")
        await self.keyword_use_cases.load_keywords_from_config()
        self.logger.info("关键字系统初始化完成")

        self.logger.info("初始化定时器管理器...")
        await self.timer_manager.start()
        self.logger.info("定时器管理器初始化完成")

        if self.user_memory:
            self.logger.info("初始化记忆管理器...")
            await self.user_memory.start()
            self.logger.info("记忆管理器初始化完成")

        self.logger.info("启动控制台输入线程...")
        input_thread = threading.Thread(target=self._console_input)
        input_thread.daemon = True
        input_thread.start()
        spool_thread = threading.Thread(target=self._spool_input_loop)
        spool_thread.daemon = True
        spool_thread.start()
        self.logger.info("控制台输入线程已启动")

        await self._detect_initial_room_state()

        self.init_runtime_queue()
        self.loop = asyncio.get_running_loop()

        self.logger.info("开始主监控循环...")

        stale_excs = self._stale_element_exceptions or ()
        driver_excs = self._driver_exceptions or ()

        while self.is_running:
            try:
                self._drain_agent_command_spool()
                await self.runtime_input.drain()

                if self.runtime_input.paused:
                    await asyncio.sleep(0.5)
                    continue

                if self.runtime_queue_drainer:
                    await self.runtime_queue_drainer.drain()

                outcome = await self.event_manager.process_current_screen()
                if outcome["page_source"]:
                    await self._update_status_from_screen(outcome["screen"])

                error_count = 0
                if self.soul_handler.error_count > 9:
                    self.soul_handler.log_error(
                        f"[start_monitoring]too many errors, try to rerun, traceback: {traceback.format_exc()}"
                    )
                    return False

                await asyncio.sleep(1)
            except KeyboardInterrupt:
                if not self.in_console_mode:
                    self.logger.info("Entering console mode. Press Ctrl+C to exit...")
                    self.in_console_mode = True
                else:
                    self.logger.info("Stopping the monitoring...")
                    self.is_running = False
                    return True
            except stale_excs:
                self.soul_handler.log_error(
                    f"[start_monitoring]stale element, traceback: {traceback.format_exc()}"
                )
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling() or not self.runtime_input.paused:
                    raise
                self.logger.info("!stop 中断了本轮处理，运行时进入暂停")
            except driver_excs:
                self.soul_handler.log_error(
                    f"[start_monitoring]unknown error, traceback: {traceback.format_exc()}"
                )
                error_count += 1
                if error_count > 9:
                    self.is_running = False
                    return False
        return None

    async def stop(self) -> None:
        """Stop the runtime loop."""
        self.is_running = False

        if self._non_ui_task:
            self._non_ui_task.cancel()
            try:
                await self._non_ui_task
            except asyncio.CancelledError:
                pass

        if self.timer_manager and self.timer_manager.is_running():
            await self.timer_manager.stop()
        if self.user_memory:
            await self.user_memory.stop()
        if self.logger:
            self.logger.info("Application stopped")
