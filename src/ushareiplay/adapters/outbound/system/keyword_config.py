"""关键字预设文件（`config/keywords.yaml`）的 YAML 读取适配器。"""

from pathlib import Path
from typing import Optional

import yaml

from ushareiplay.modules.command.ports import KeywordConfigSource


class YamlKeywordConfigSource(KeywordConfigSource):
    def __init__(self, path: Path | str = Path("config/keywords.yaml")):
        self._path = Path(path)

    def load(self) -> Optional[dict]:
        if not self._path.exists():
            return None
        with open(self._path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
