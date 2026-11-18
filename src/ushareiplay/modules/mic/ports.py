"""麦克风出站端口：Soul 的麦克风 UI 由 Appium 适配器实现。"""

from abc import ABC, abstractmethod


class MicControl(ABC):
    """麦克风状态读取与开关。"""

    @abstractmethod
    def state(self, *, wait: bool = False) -> bool | None:
        """当前状态：True 开麦、False 闭麦、None 无法判定。

        `wait=True` 时等待按钮渲染（要动手改麦克风的路径）；非阻塞读态用于
        静音保护这类「读不到就跳过」的决策。
        """

    @abstractmethod
    def set_active(self, enable: bool, *, report_noop: bool = False) -> dict:
        """把麦克风设为目标状态；需要开麦时先完成必要的前置准备。

        Returns:
            {'state': '1'|'0'} 或 {'error': <公屏文案>}
        """

    @abstractmethod
    def ensure_active(self) -> dict:
        """无条件开麦（幂等），供播放静音保护的兜底恢复使用；异常转为 error。"""
