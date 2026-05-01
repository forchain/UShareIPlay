from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ushareiplay.core.paths import artifacts_paths


EVENTS_SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_run_id() -> str:
    # short, filesystem-friendly
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]


@dataclass
class Observability:
    run_id: str
    artifacts_root_rel: str = "artifacts"

    def paths(self):
        return artifacts_paths(self.run_id, root_rel=self.artifacts_root_rel)

    def emit(
        self,
        event: str,
        *,
        level: str = "INFO",
        ctx: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "schema_version": EVENTS_SCHEMA_VERSION,
            "ts": _now_iso(),
            "level": level,
            "event": event,
            "run_id": self.run_id,
            "ctx": ctx or {},
        }
        if trace_id:
            payload["trace_id"] = trace_id

        p = self.paths().events_jsonl
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def write_status(self, status: Dict[str, Any]) -> Path:
        p = self.paths().status_json
        p.parent.mkdir(parents=True, exist_ok=True)
        body = dict(status)
        body.setdefault("schema_version", STATUS_SCHEMA_VERSION)
        body.setdefault("run_id", self.run_id)
        body.setdefault("ts", _now_iso())
        p.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p

