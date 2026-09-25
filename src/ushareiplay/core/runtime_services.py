import queue
import traceback
from dataclasses import dataclass
from pathlib import Path
import json

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    expand_queue_text,
    format_manual_message,
    is_manual_operator,
)
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.models.message_info import MessageInfo


@dataclass(frozen=True)
class QueueRouting:
    """一条运行时文本展开后的去向。

    Attributes:
        commands: 需要执行或入队的命令消息
        screen_texts: 要发到公屏的普通发言（已按来源加好 [人工] 标记）
        suppressed: 被静默前缀吞掉的发言，仅用于日志
    """

    commands: tuple[MessageInfo, ...] = ()
    screen_texts: tuple[str, ...] = ()
    suppressed: tuple[str, ...] = ()


def route_queue_text(
    text: str,
    nickname: str,
    *,
    source: str | None = None,
    silent: bool = False,
    sleep_exempt: bool = False,
) -> QueueRouting:
    """展开 queue 文法，并把每条结果路由到「命令 / 公屏 / 静默抑制」。

    监控循环内联过一份这样的路由，`CommandManager.execute_runtime_queue_messages`
    里还有一份；两份对「什么算命令」和「公屏文案怎么加标记」必须一致，因此只剩
    这一个实现 —— 两类调用方只在拿到命令之后分道扬镳（一个执行、一个入队）。
    """
    commands: list[MessageInfo] = []
    screen_texts: list[str] = []
    suppressed: list[str] = []

    for result in expand_queue_text(
        text, nickname, silent=silent, sleep_exempt=sleep_exempt
    ):
        if result.kind == ChatIntakeKind.COMMAND:
            # 只有触发符、没有内容的不算命令（与 execute_chat_scan 的判定一致）
            if not result.text.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                continue
            commands.append(
                MessageInfo(
                    content=result.text,
                    nickname=result.nickname,
                    silent=result.silent,
                    private_reply=result.private_reply,
                    sleep_exempt=result.sleep_exempt,
                    source=source,
                )
            )
        elif result.silent:
            suppressed.append(result.text)
        else:
            screen_texts.append(
                format_manual_message(result.text)
                if is_manual_operator(nickname, source)
                else result.text
            )

    return QueueRouting(tuple(commands), tuple(screen_texts), tuple(suppressed))


class RuntimeQueueDrainer:
    """Drain MessageQueue from runtime loop (single authoritative path)."""

    def __init__(self, *, handler, command_manager, send_screen_message, obs=None, logger=None):
        self.handler = handler
        self.command_manager = command_manager
        self.send_screen_message = send_screen_message
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
            send_screen_message=self.send_screen_message,
        )

        if self.obs:
            self.obs.emit(
                "queue.drain.end",
                ctx={"count": len(queue_messages), "command_count": command_count},
            )

        return len(queue_messages), command_count


class RuntimeInputPipeline:
    """运行时输入管线：把 console / agent 队列里的条目变成命令与公屏消息。

    监控循环原先内联了这段逻辑（约 75 行）：三种条目形状（dict / tuple / 裸
    字符串）的归一化、房主昵称默认、queue 文法展开、`!stop` / `!timer` /
    `!dump` 三个 meta 命令，以及静默抑制与 [人工] 标记。循环因此既要驱动事件
    循环，又要在自己身体里维护一套小型状态机。

    管线只做输入侧的事：把队列排空、把文本路由到 `MessageQueue` 或公屏。
    命令的执行仍然由 `RuntimeQueueDrainer` + `CommandManager` 负责。
    """

    def __init__(
        self,
        *,
        input_queue,
        room_owner_provider,
        logger,
        send_screen_message,
        timer_manager=None,
        obs=None,
        dump_artifacts=None,
    ):
        self.input_queue = input_queue
        self.room_owner_provider = room_owner_provider
        self.logger = logger
        self.send_screen_message = send_screen_message
        self.timer_manager = timer_manager
        self.obs = obs
        self._dump_artifacts = dump_artifacts
        self.paused = False

    async def drain(self) -> None:
        """排空队列中的条目（非阻塞；空队列立即返回）。"""
        while True:
            try:
                item = self.input_queue.get_nowait()
            except queue.Empty:
                return
            await self._handle_item(item)

    def _normalize(self, item) -> tuple[str, str, str]:
        """dict / tuple / 裸字符串 → (message, source, nickname)。

        未署名或署名为 `Console` 的条目按房主身份处理。
        """
        owner = self.room_owner_provider()
        if isinstance(item, dict):
            message = item.get("content", "")
            source = item.get("source", "console")
            raw_nick = item.get("nickname")
            nickname = str(owner if not raw_nick or raw_nick == "Console" else raw_nick)
        elif isinstance(item, tuple):
            message, source = item
            nickname = owner
        else:
            message, source = item, "console"
            nickname = owner
        return message, source, nickname

    async def _handle_item(self, item) -> None:
        message, source, nickname = self._normalize(item)
        if not message.strip():
            return
        if await self._handle_meta_command(message, source):
            return
        await self._route_text(message, source, nickname)

    async def _handle_meta_command(self, message: str, source: str) -> bool:
        """处理 `!stop` / `!timer` / `!dump`；返回 True 表示已被消费。"""
        if message == '!stop':
            self.paused = not self.paused
            self.logger.critical(f'paused: {self.paused}')
            return True

        if message == '!timer':
            if self.timer_manager is None:
                return True
            if self.timer_manager.is_running():
                await self.timer_manager.stop()
            else:
                await self.timer_manager.start()
            self.logger.critical(f'is_running:{self.timer_manager.is_running()}')
            return True

        if message == '!dump':
            if self._dump_artifacts is None:
                return True
            try:
                await self._dump_artifacts(reason=source)
            except Exception:
                if self.obs:
                    self.obs.emit(
                        "artifact.dump.error",
                        level="ERROR",
                        ctx={"error": traceback.format_exc(), "reason": source},
                    )
            return True

        return False

    async def _route_text(self, message: str, source: str, nickname: str) -> None:
        routing = route_queue_text(message, nickname, source=source)

        queue = MessageQueue.instance()
        for message_info in routing.commands:
            await queue.put_message(message_info)
            if self.obs:
                self.obs.emit(
                    "queue.enqueue",
                    ctx={
                        "source": source,
                        "content": message_info.content,
                        "nickname": message_info.nickname,
                    },
                )
            self.logger.info(f"{source} message added to queue: {message_info.content}")

        for screen_text in routing.screen_texts:
            self.send_screen_message(screen_text)

        for suppressed in routing.suppressed:
            self.logger.info(f"Silent queued message suppressed: {suppressed}")


class AgentCommandSpool:
    def __init__(self, *, input_queue, command_dir: Path, obs=None, config=None):
        self.input_queue = input_queue
        self.command_dir = command_dir
        self.obs = obs
        self.config = config

    def drain(self) -> None:
        try:
            from ushareiplay.core.roles import RolePolicy
            owner = RolePolicy(self.config).room_owner
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
                    raw_nick = parsed.get("nickname")
                    nickname = str(owner if not raw_nick or raw_nick == "Console" else raw_nick)
                    payload = {
                        "content": str(parsed.get("content")),
                        "source": "agent_spool",
                        "nickname": nickname,
                    }
                else:
                    payload = {"content": raw, "source": "agent_spool", "nickname": owner}

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
