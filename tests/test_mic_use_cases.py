"""Mic 领域规则与切换用例（内存端口）。

外部行为：content-desc 决定开/闭麦；目标状态已达成时默认幂等成功，
只有 `:mic` 显式要求时才把「已开麦/已闭麦」作为提示返回。
"""

from ushareiplay.modules.mic.domain import (
    MIC_ACTIVE_DESC,
    MIC_INACTIVE_DESC,
    MIC_STATUS_UNAVAILABLE,
    noop_result,
    state_from_desc,
    state_result,
)
from ushareiplay.modules.mic.use_cases import ToggleMic
from tests.fakes.in_memory_mic_control import InMemoryMicControl


# --------------------------------------------------------------------------
# 状态读取
# --------------------------------------------------------------------------

def test_active_desc_means_mic_is_open():
    assert state_from_desc(MIC_ACTIVE_DESC) is True


def test_inactive_desc_means_mic_is_closed():
    assert state_from_desc(MIC_INACTIVE_DESC) is False


def test_unrecognized_desc_is_unknown():
    assert state_from_desc("未知按钮") is None
    assert state_from_desc(None) is None


# --------------------------------------------------------------------------
# no-op 报告规则
# --------------------------------------------------------------------------

def test_reached_target_is_silent_success_by_default():
    assert noop_result(True, report_noop=False) == {"state": "1"}
    assert noop_result(False, report_noop=False) == {"state": "0"}


def test_reached_target_reports_already_on_or_off_when_asked():
    assert noop_result(True, report_noop=True) == {"error": "Microphone is already on"}
    assert noop_result(False, report_noop=True) == {"error": "Microphone is already off"}


def test_setup_that_opened_the_mic_is_success_not_a_noop_report():
    """抢麦就座后麦克风已随座位自动打开：这是成功，不是「已开麦」。"""
    assert noop_result(True, report_noop=True, opened_during_setup=True) == {"state": "1"}


def test_state_result_uses_protocol_shape():
    assert state_result(True) == {"state": "1"}
    assert state_result(False) == {"state": "0"}


# --------------------------------------------------------------------------
# 切换用例（内存端口）
# --------------------------------------------------------------------------

def test_toggle_flips_a_closed_mic_on_and_reports_noops():
    mic = InMemoryMicControl(state=False)
    result = ToggleMic(mic).toggle()

    assert result == {"state": "1"}
    assert mic.calls == [(True, True)]
    assert mic.state_waits == [True]


def test_toggle_flips_an_open_mic_off():
    mic = InMemoryMicControl(state=True)
    result = ToggleMic(mic).toggle()

    assert result == {"state": "0"}
    assert mic.calls == [(False, True)]


def test_toggle_does_not_touch_the_mic_when_status_is_unreadable():
    mic = InMemoryMicControl(state=None)
    result = ToggleMic(mic).toggle()

    assert result == {"error": MIC_STATUS_UNAVAILABLE}
    assert mic.calls == []


def test_set_delegates_the_explicit_target_with_noop_reporting():
    mic = InMemoryMicControl(state=False)

    assert ToggleMic(mic).set(True) == {"state": "1"}
    assert mic.calls == [(True, True)]
