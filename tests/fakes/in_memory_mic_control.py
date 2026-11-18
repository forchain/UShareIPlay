"""`MicControl` 的内存替身：记录动作，不碰任何 UI。"""

from ushareiplay.modules.mic.ports import MicControl


class InMemoryMicControl(MicControl):
    def __init__(self, state: bool | None = None):
        self.active = state
        self.calls: list[tuple] = []
        self.state_waits: list[bool] = []

    def state(self, *, wait: bool = False) -> bool | None:
        self.state_waits.append(wait)
        return self.active

    def set_active(self, enable: bool, *, report_noop: bool = False) -> dict:
        self.calls.append((enable, report_noop))
        self.active = enable
        return {"state": "1" if enable else "0"}

    def ensure_active(self) -> dict:
        self.calls.append(("ensure", None))
        self.active = True
        return {"state": "1"}
