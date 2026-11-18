"""麦克风业务包：状态规则、控制端口与切换用例。"""

from ushareiplay.modules.mic.domain import (
    MIC_ACTIVE_DESC,
    MIC_BUTTON_NOT_FOUND,
    MIC_INACTIVE_DESC,
    MIC_NOT_SEATED,
    MIC_STATUS_UNAVAILABLE,
    noop_result,
    state_from_desc,
    state_result,
)
from ushareiplay.modules.mic.ports import MicControl
from ushareiplay.modules.mic.use_cases import ToggleMic

__all__ = [
    "MIC_ACTIVE_DESC",
    "MIC_BUTTON_NOT_FOUND",
    "MIC_INACTIVE_DESC",
    "MIC_NOT_SEATED",
    "MIC_STATUS_UNAVAILABLE",
    "MicControl",
    "ToggleMic",
    "noop_result",
    "state_from_desc",
    "state_result",
]
