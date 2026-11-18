"""Soul App 麦克风 UI 适配器：状态读取与开闭麦点击。

两个不变量：
1. 「开麦 = content-desc 是『闭麦按钮』」
2. 「开麦前必须先上麦」（不在麦位时界面只提供抢麦入口，直接点开麦会失败）

元素查询保持即用即查：每次调用都重新定位，绝不缓存 WebElement。
"""

import logging
import traceback
from typing import Optional

from ushareiplay.modules.mic.domain import (
    MIC_BUTTON_NOT_FOUND,
    MIC_NOT_SEATED,
    MIC_STATUS_UNAVAILABLE,
    noop_result,
    state_from_desc,
)
from ushareiplay.modules.mic.ports import MicControl


class SoulMicControl(MicControl):
    """麦克风状态与开关的 Soul 实现（ADR-0007 的接缝）。"""

    def __init__(self, handler):
        self._soul_handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def soul_handler(self):
        return self._soul_handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._soul_handler, "logger", None) or logging.getLogger("SoulMicControl")
        return self._logger

    def state(self, *, wait: bool = False) -> Optional[bool]:
        """麦克风是否开麦：True 开麦、False 闭麦、None 无法判定。

        会先切到 Soul App：调用方（静音保护、:mic、:pause）都是在 Soul 侧做
        麦克风决策，而此刻前台可能是 QQ 音乐。

        Args:
            wait: 按钮还没渲染出来时是否等它（最长 10 秒）。要动手改麦克风的
                路径都该等 —— 刚就座、刚进房时按钮可能还没出现，即时读会立刻
                报「找不到按钮」。静音保护读态保持非阻塞：它只是决定要不要闭麦，
                等不到就应该直接跳过。
        """
        if not self.soul_handler.key_actions.switch_to_app():
            return None
        if wait:
            element = self.soul_handler.element_finder.wait_for_element('toggle_mic')
        else:
            element = self.soul_handler.element_finder.try_find_element('toggle_mic', log=False)
        if not element:
            return None
        desc = self.soul_handler.element_finder.try_get_attribute(element, 'content-desc')
        return state_from_desc(desc)

    def set_active(self, enable: bool, *, report_noop: bool = False) -> dict:
        """把麦克风设为目标状态，需要开麦时先确保已在麦位。

        Args:
            enable: True 开麦、False 闭麦
            report_noop: 目标状态已达成时是否返回 error。`:mic` 用它保持
                「已开麦/已闭麦」的提示；静音保护、`:pause` 这类内部调用
                使用默认的幂等成功语义（返回当前状态，不报错）。
        """
        opened_during_setup = False
        if enable and not self.soul_handler.is_on_seat():
            # 开麦前先确认已在麦位：不在麦位时界面只提供抢麦入口，
            # 直接点击开麦按钮会失败或抛错。
            if not self.soul_handler.ensure_on_seat():
                return {'error': MIC_NOT_SEATED}
            opened_during_setup = True

        current = self.state(wait=True)
        if current is None:
            # 两种「读不到状态」的原因对应两条既有报错文案，保持它们不变：
            # 按钮本身不在（例如不在派对房）比 desc 异常更值得单独提示。
            if not self.soul_handler.element_finder.try_find_element('toggle_mic', log=False):
                return {'error': MIC_BUTTON_NOT_FOUND}
            return {'error': MIC_STATUS_UNAVAILABLE}

        if current == enable:
            if opened_during_setup and enable:
                # 抢麦就座后麦克风已随座位自动打开，目标状态已达成，不算「已开麦」报错
                self.logger.info("Mic already on after seating")
            return noop_result(
                enable, report_noop=report_noop, opened_during_setup=opened_during_setup
            )

        button = self.soul_handler.element_finder.wait_for_element_clickable('toggle_mic')
        if not button:
            return {'error': MIC_BUTTON_NOT_FOUND}

        button.click()
        self.logger.info(f"Set mic to {'1' if enable else '0'}")
        return {'state': '1' if enable else '0'}

    def ensure_active(self) -> dict:
        """无条件开麦（幂等），播放静音保护的兜底恢复用它。

        就是 `set_active(True)`：不在麦位先抢麦、抢麦后若麦克风仍未开再点开。
        区别只在于失败时自己吞掉异常并返回 error —— 兜底恢复不应把异常抛回
        到已经出错的播放流程里。
        """
        try:
            return self.set_active(True)
        except Exception as e:
            self.logger.error(f"Error ensuring mic is active: {traceback.format_exc()}")
            return {'error': str(e)}
