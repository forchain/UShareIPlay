"""`RoomStateStore` 的 JSON 文件实现（`data/room_state.json`）。

文件路径与旧 `RoomState` 完全一致，读写失败仍按旧行为静默忽略：这份状态是
「下次启动优先去哪间房」的提示，不是业务事实。
"""

import json
from pathlib import Path
from typing import Optional

from ushareiplay.modules.room.ports import RoomStateStore


class JsonRoomStateStore(RoomStateStore):
    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else Path("data/room_state.json")

    def load_expected_party_id(self) -> Optional[str]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return data.get("expected_party_id")
        except Exception:
            pass
        return None

    def save_expected_party_id(self, party_id: Optional[str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"expected_party_id": party_id}
            self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
