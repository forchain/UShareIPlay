"""麦克风状态的唯一实现。

两个不变量原先各有三份分歧实现：

1. 「开麦 = content-desc 是『闭麦按钮』」
   - `PlaybackMuting._mic_state()`
   - `MicCommand.toggle_mic()`
   - `SoulHandler.ensure_mic_active()`
2. 「开麦前必须先上麦」（不在麦位时界面只提供抢麦入口，直接点开麦会失败）
   - `MicCommand.toggle_mic()` 有
   - `SoulHandler.ensure_mic_active()` 有（但走的是另一套分支）
   - `PlaybackMuting` 完全没有

而名字最相关的本模块只有一个盲点击（`toggle_mic` 不看状态），它的
`get_mic_status()` 还会因为漏 import `traceback` 而 NameError。

现在接口只有三个方法：

    state() -> True 开麦 / False 闭麦 / None 无法判定
    set_active(enable)  -> 设为目标状态（开麦时自动先确保在麦位）
    ensure_active()     -> 无条件开麦（播放静音保护的兜底恢复用它）

`playback_muting`、`:mic`、`:pause` 与 `SoulHandler.ensure_mic_active` 的名称
都收敛到这里；`UIActions.toggle_mic`（盲点击）随之删除。
"""

import traceback
from typing import Optional

from ushareiplay.core.singleton import Singleton


class MicManager(Singleton):
    """麦克风状态与开关的唯一实现（见 ADR-0007 的接缝约定）。"""

    MIC_ACTIVE_DESC = "闭麦按钮"    # content-desc 为「闭麦按钮」表示当前开麦
    MIC_INACTIVE_DESC = "开麦按钮"  # content-desc 为「开麦按钮」表示当前闭麦

    def __init__(self):
        # 延迟解析的依赖；测试可直接注入替身（见 ADR-0004 的注入约定）
        self._soul_handler = None
        self._logger = None

    @property
    def soul_handler(self):
        if self._soul_handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._soul_handler = SoulHandler.instance()
        return self._soul_handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = self.soul_handler.logger
        return self._logger

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @classmethod
    def _state_from_desc(cls, desc: Optional[str]) -> Optional[bool]:
        if desc == cls.MIC_ACTIVE_DESC:
            return True
        if desc == cls.MIC_INACTIVE_DESC:
            return False
        return None

    def state(self) -> Optional[bool]:
        """麦克风是否开麦：True 开麦、False 闭麦、None 无法判定。

        会先切到 Soul App：调用方（静音保护、:mic、:pause）都是在 Soul 侧做
        麦克风决策，而此刻前台可能是 QQ 音乐。
        """
        if not self.soul_handler.key_actions.switch_to_app():
            return None
        element = self.soul_handler.element_finder.try_find_element('toggle_mic', log=False)
        if not element:
            return None
        desc = self.soul_handler.element_finder.try_get_attribute(element, 'content-desc')
        return self._state_from_desc(desc)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def set_active(self, enable: bool, *, report_noop: bool = False) -> dict:
        """把麦克风设为目标状态，需要开麦时先确保已在麦位。

        Args:
            enable: True 开麦、False 闭麦
            report_noop: 目标状态已达成时是否返回 error。`:mic` 用它保持
                「已开麦/已闭麦」的提示；静音保护、`:pause` 这类内部调用
                使用默认的幂等成功语义（返回当前状态，不报错）。

        Returns:
            {'state': '1'|'0'} 或 {'error': ...}
        """
        just_seated = False
        if enable and not self.soul_handler.is_on_seat():
            # 开麦前先确认已在麦位：不在麦位时界面只提供抢麦入口，
            # 直接点击开麦按钮会失败或抛错。
            if not self.soul_handler.ensure_on_seat():
                return {'error': 'Failed to grab mic, not seated yet'}
            just_seated = True

        current = self.state()
        if current is None:
            # 两种「读不到状态」的原因对应两条既有报错文案，保持它们不变：
            # 按钮本身不在（例如不在派对房）比 desc 异常更值得单独提示。
            if not self.soul_handler.element_finder.try_find_element('toggle_mic', log=False):
                return {'error': 'Microphone button not found'}
            return {'error': 'Failed to get mic status'}

        target = "1" if enable else "0"
        if current == enable:
            if just_seated and enable:
                # 抢麦就座后麦克风已随座位自动打开，目标状态已达成，不算「已开麦」报错
                self.logger.info("Mic already on after seating")
                return {'state': target}
            if report_noop:
                return {'error': f'Microphone is already {"on" if enable else "off"}'}
            return {'state': target}

        button = self.soul_handler.element_finder.wait_for_element_clickable('toggle_mic')
        if not button:
            return {'error': 'Microphone button not found'}

        button.click()
        self.logger.info(f"Set mic to {target}")
        return {'state': target}

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
