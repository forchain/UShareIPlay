import re
import traceback
from pathlib import Path

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.models.message_info import MessageInfo


class RuntimeQueueDrainer:
    """Drain MessageQueue from runtime loop (single authoritative path)."""

    def __init__(self, *, handler, command_manager, obs=None, logger=None):
        self.handler = handler
        self.command_manager = command_manager
        self.obs = obs
        self.logger = logger or getattr(handler, "logger", None)

    async def drain(self) -> tuple[int, int]:
        queue_messages = await MessageQueue.instance().get_all_messages()
        if not queue_messages:
            return 0, 0

        if self.obs:
            self.obs.emit("queue.drain.start", ctx={"count": len(queue_messages)})

        command_messages = []
        for message_info in queue_messages.values():
            parts = (message_info.content or "").split(";")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                part = part.replace("{user_name}", message_info.nickname)
                if part.startswith((":", "：")):
                    command_messages.append(
                        MessageInfo(content=part, nickname=message_info.nickname)
                    )
                else:
                    self.handler.send_message(part)

        if command_messages:
            await self.command_manager.handle_message_commands(command_messages)

        if self.obs:
            self.obs.emit(
                "queue.drain.end",
                ctx={"count": len(queue_messages), "command_count": len(command_messages)},
            )

        return len(queue_messages), len(command_messages)


class AgentCommandSpool:
    def __init__(self, *, input_queue, command_dir: Path, obs=None):
        self.input_queue = input_queue
        self.command_dir = command_dir
        self.obs = obs

    def drain(self) -> None:
        try:
            self.command_dir.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.command_dir.glob("*.cmd")):
                try:
                    message = path.read_text(encoding="utf-8").rstrip("\r\n")
                    path.unlink(missing_ok=True)
                except Exception:
                    if self.obs:
                        self.obs.emit(
                            "agent.inject.error",
                            level="ERROR",
                            ctx={"path": str(path), "error": traceback.format_exc()},
                        )
                    continue
                if message and message.strip():
                    self.input_queue.put((message, "agent_spool"))
                    if self.obs:
                        self.obs.emit(
                            "agent.inject.received",
                            ctx={"source": "agent_spool", "content": message},
                        )
        except Exception:
            if self.obs:
                self.obs.emit(
                    "agent.inject.error",
                    level="ERROR",
                    ctx={"error": traceback.format_exc()},
                )


class StatusReporter:
    def __init__(self, *, config, ui_lock, obs, soul_handler=None, timer_manager=None):
        self.config = config
        self.ui_lock = ui_lock
        self.obs = obs
        self.soul_handler = soul_handler
        self.timer_manager = timer_manager

    async def update(self, *, page_source: str, event_manager, automation=None) -> None:
        try:
            pkgs = event_manager._packages_from_page_source(page_source)
            soul_pkg = event_manager._soul_package_name()
            qq_pkg = (self.config.get("qq_music", {}) or {}).get(
                "package_name", "com.tencent.qqmusic"
            )
            launchers = set(event_manager._launcher_packages())

            foreground_app = "Unknown"
            if pkgs:
                if soul_pkg in pkgs:
                    foreground_app = "Soul"
                elif qq_pkg in pkgs:
                    foreground_app = "QQMusic"
                elif pkgs & launchers:
                    foreground_app = "Launcher"

            anchors = []
            soul_elements = (self.config.get("soul", {}) or {}).get("elements", {}) or {}

            def selector_present(selector: str) -> bool:
                if not selector or not isinstance(selector, str):
                    return False
                if selector in page_source:
                    return True
                if selector.startswith("//") and "@resource-id" in selector:
                    m = re.search(r'@resource-id\s*=\s*"([^"]+)"', selector)
                    if m and m.group(1) and m.group(1) in page_source:
                        return True
                return False

            for key in ("message_content", "input_box_entry", "input_box"):
                sel = soul_elements.get(key)
                if sel and selector_present(sel):
                    anchors.append(key)

            ui_lock_state = "locked" if (self.ui_lock and self.ui_lock.locked()) else "unlocked"
            queue_size = MessageQueue.instance().get_queue_size()

            soul_ui_state = "Unknown"
            if foreground_app == "Soul":
                soul_ui_state = "InChatReady" if "message_content" in anchors else "InUnknownPage"

            status = {
                "foreground_app": foreground_app,
                "soul_ui_state": soul_ui_state,
                "qqmusic_ui_state": "Unknown",
                "anchors": anchors,
                "pipeline": {"ui_lock": ui_lock_state, "queue_size": queue_size},
                "business": {
                    "party_id_current": getattr(self.soul_handler, "party_id", None)
                    if self.soul_handler
                    else None,
                    "party_id_target": (self.config.get("soul", {}) or {}).get("default_party_id"),
                    "timers_running": bool(self.timer_manager and self.timer_manager.is_running()),
                    "playback_info_summary": None,
                },
            }
            self.obs.write_status(status)
            self.obs.emit("state.snapshot", ctx={"foreground_app": foreground_app, "anchors": anchors})
            if foreground_app == "Soul" and soul_ui_state == "InChatReady":
                self.obs.emit(
                    "state.ready",
                    ctx={
                        "name": "CommandReady",
                        "anchors": anchors,
                        "foreground_app": foreground_app,
                    },
                )
                if automation:
                    await automation.on_command_ready()
        except Exception:
            self.obs.emit("state.snapshot.error", level="ERROR", ctx={"error": traceback.format_exc()})
