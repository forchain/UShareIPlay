import traceback
from pathlib import Path
import json

from ushareiplay.core.message_queue import MessageQueue


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

        command_count = await self.command_manager.execute_runtime_queue_messages(
            queue_messages.values(),
            send_screen_message=self.handler.send_message,
        )

        if self.obs:
            self.obs.emit(
                "queue.drain.end",
                ctx={"count": len(queue_messages), "command_count": command_count},
            )

        return len(queue_messages), command_count


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
                    raw = path.read_text(encoding="utf-8").rstrip("\r\n")
                    path.unlink(missing_ok=True)
                except Exception:
                    if self.obs:
                        self.obs.emit(
                            "agent.inject.error",
                            level="ERROR",
                            ctx={"path": str(path), "error": traceback.format_exc()},
                        )
                    continue
                if not raw or not raw.strip():
                    continue

                payload = None
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None

                if isinstance(parsed, dict) and parsed.get("content"):
                    payload = {
                        "content": str(parsed.get("content")),
                        "source": "agent_spool",
                        "nickname": str(parsed.get("nickname") or "Console"),
                    }
                else:
                    payload = {"content": raw, "source": "agent_spool", "nickname": "Console"}

                self.input_queue.put(payload)
                if self.obs:
                    self.obs.emit(
                        "agent.inject.received",
                        ctx={
                            "source": "agent_spool",
                            "content": payload["content"],
                            "nickname": payload["nickname"],
                        },
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

    async def update(self, *, screen: dict, automation=None) -> None:
        try:
            foreground_app = screen["foreground_app"]
            anchors = screen["anchors"]
            ui_lock_state = "locked" if (self.ui_lock and self.ui_lock.locked()) else "unlocked"
            queue_size = MessageQueue.instance().get_queue_size()

            status = {
                "foreground_app": foreground_app,
                "soul_ui_state": screen["soul_ui_state"],
                "qqmusic_ui_state": screen["qqmusic_ui_state"],
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
            if foreground_app == "Soul" and screen["soul_ui_state"] == "InChatReady":
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
