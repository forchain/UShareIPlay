"""麦克风用例：目标状态决策，UI 动作由注入的 `MicControl` 完成。"""

from ushareiplay.modules.mic.domain import MIC_STATUS_UNAVAILABLE
from ushareiplay.modules.mic.ports import MicControl


class ToggleMic:
    """`:mic` 的切换决策；显式目标与裸切换都走 `set_active(report_noop=True)`。"""

    def __init__(self, mic: MicControl):
        self._mic = mic

    def set(self, enable: bool) -> dict:
        return self._mic.set_active(enable, report_noop=True)

    def toggle(self) -> dict:
        """在当前状态上取反；状态读不到时报既有文案且不触碰麦克风。"""
        current = self._mic.state(wait=True)
        if current is None:
            return {"error": MIC_STATUS_UNAVAILABLE}
        return self._mic.set_active(not current, report_noop=True)
