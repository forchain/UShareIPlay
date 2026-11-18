"""麦克风领域：状态判定与已达成目标时的报告规则。

本包只描述麦克风本身：开麦/闭麦、状态不可判定、以及目标已达成时是否把
「已开麦/已闭麦」当成提示返回。
"""

MIC_ACTIVE_DESC = "闭麦按钮"    # content-desc 为「闭麦按钮」表示当前开麦
MIC_INACTIVE_DESC = "开麦按钮"  # content-desc 为「开麦按钮」表示当前闭麦

MIC_BUTTON_NOT_FOUND = "Microphone button not found"
MIC_STATUS_UNAVAILABLE = "Failed to get mic status"
MIC_GRAB_FAILED = "Failed to grab mic, not seated yet"


def state_from_desc(desc: str | None) -> bool | None:
    """把开关按钮的 content-desc 翻译成麦克风状态：True 开麦 / False 闭麦 / None 未知。"""
    if desc == MIC_ACTIVE_DESC:
        return True
    if desc == MIC_INACTIVE_DESC:
        return False
    return None


def state_result(enable: bool) -> dict:
    """成功结果沿用既有公屏模板字段。"""
    return {"state": "1" if enable else "0"}


def noop_result(
    enable: bool, *, report_noop: bool, opened_during_setup: bool = False
) -> dict:
    """目标状态已达成时的结果。

    默认幂等成功（静音保护、`:pause` 只关心最终状态）；`report_noop=True`
    的 `:mic` 才把「已开麦/已闭麦」作为提示返回。开麦前置准备本身已把麦克风
    打开时不算 no-op：用户要的开麦已经发生了。
    """
    if report_noop and not (opened_during_setup and enable):
        return {"error": f'Microphone is already {"on" if enable else "off"}'}
    return state_result(enable)
