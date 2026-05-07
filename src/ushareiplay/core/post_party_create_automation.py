from __future__ import annotations

import traceback
import logging
from typing import List, Optional

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.models import MessageInfo


class PostPartyCreateAutomation:
    """
    新建派对成功后的自动化：等待 CommandReady 后（可配置），按序投递命令到 MessageQueue。

    约束：
    - 动作仅支持“命令字符串 → MessageQueue”
    - 仅对“新建派对成功”触发一次（AND+once 门闩语义）
    """

    def __init__(self, controller):
        self.controller = controller

        # Latch state (AND + once)
        self._party_created_new: bool = False
        self._command_ready: bool = False
        self._fired: bool = False

    def _cfg(self) -> dict:
        soul_cfg = (self.controller.config.get("soul", {}) or {}) if self.controller else {}
        return (soul_cfg.get("post_party_create", {}) or {})

    def _enabled(self) -> bool:
        return bool(self._cfg().get("enabled", False))

    def _wait_for_ready(self) -> bool:
        return bool(self._cfg().get("wait_for_command_ready", True))

    def _commands(self) -> List[str]:
        cmds = self._cfg().get("commands", []) or []
        # tolerate wrong types
        if not isinstance(cmds, list):
            return []
        return [c for c in cmds if isinstance(c, str) and c.strip()]

    def _log_info(self, msg: str) -> None:
        logger = getattr(self.controller, "logger", None)
        if logger:
            logger.info(msg)
        else:
            logging.getLogger(__name__).info(msg)

    def _log_warning(self, msg: str) -> None:
        logger = getattr(self.controller, "logger", None)
        if logger:
            logger.warning(msg)
        else:
            logging.getLogger(__name__).warning(msg)

    async def on_party_created_new(self) -> None:
        self._party_created_new = True
        obs = getattr(self.controller, "obs", None)
        if obs:
            obs.emit(
                "automation.post_party_create.signal",
                ctx={"signal": "party_created_new"},
            )
        await self._maybe_fire(trigger="party_created_new")

    async def on_command_ready(self) -> None:
        self._command_ready = True
        obs = getattr(self.controller, "obs", None)
        if obs:
            obs.emit(
                "automation.post_party_create.signal",
                ctx={"signal": "command_ready"},
            )
        await self._maybe_fire(trigger="command_ready")

    async def _maybe_fire(self, trigger: str) -> None:
        if self._fired:
            return
        if not self._enabled():
            obs = getattr(self.controller, "obs", None)
            if obs:
                obs.emit(
                    "automation.post_party_create.skipped",
                    ctx={"reason": "disabled", "trigger": trigger},
                )
            return
        if not self._party_created_new:
            return
        if self._wait_for_ready() and not self._command_ready:
            return

        cmds = self._commands()
        if not cmds:
            self._fired = True
            self._log_info("[post_party_create] enabled but commands empty; no-op")
            return

        try:
            self._log_info(
                f"[post_party_create] firing ({trigger}), commands={len(cmds)}, wait_for_ready={self._wait_for_ready()}"
            )
            queue = MessageQueue.instance()
            for cmd in cmds:
                await queue.put_message(MessageInfo(content=cmd, nickname="Console"))
            self._fired = True
            obs = getattr(self.controller, "obs", None)
            if obs:
                obs.emit(
                    "automation.post_party_create.fired",
                    ctx={"commands": cmds, "trigger": trigger, "wait_for_ready": self._wait_for_ready()},
                )
        except Exception:
            self._log_warning(f"[post_party_create] failed: {traceback.format_exc()}")
