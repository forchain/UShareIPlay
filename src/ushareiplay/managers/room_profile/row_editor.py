"""抽屉行编辑器：话题 / 公告 / 房名三条写 UI 纵切合成的**同一个**操作。

原先抽屉里的三行各自手写了一遍 ritual ——「打开编辑层 → 替换文字 → 提交 →
等落地 → 判结果 → 收尾」，三份拷贝各自漂移：

- 同一个「别人房间」在三条路上叫三个名字（`{'skipped': 'guest_room'}` /
  `{'skipped': True, 'reason': 'guest_room'}` / …），调用方因此要按调用点
  猜「哪个键是什么意思」；
- 同一个「改得太频繁」在两条路上是两句不同的话（"update topic too
  frequently" / "Update failed - still in cooldown period"），公告那条路干脆
  没有「被拒」这一档；
- 「别人房间里不许动抽屉」这个守卫在模块里被抄了十四遍，改一次判定要改十四处。

本模块把那一段收成一次操作：

    outcome = edit_row(skin, text)

`skin`（`RowSkin`）是**一行抽屉的全部数据**：怎么走进它的编辑层、输入框与
确认键是谁、提交后等多久、用哪几个元素判结果、提交被拒时收掉哪一层、对外
长什么样。`WriteOutcome` 是唯一的结局类型（`SUCCESS` / `CONFLICT` /
`RENDER_FAILED` / `SKIPPED`）—— 调用方分支这一个枚举就够了，不必再逐个键去
试探。

冷却预算、草稿记账与对外的 dict 形状**不在**这里：那些是
`RoomProfileManager` 的事。本模块只做物理动作，也不新增任何抽屉原语 ——
编辑一层仍然只用端口已有的那四样（点元素、点某个高度、等任意一个、写输入框）。

`SKIPPED` 与「失败」必须分得开：别人房间里一个点击都没发生，因此草稿留着、
预算留着、也不往公屏播报一条根本没发生过的变更。
"""

import time
import traceback
from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

from ushareiplay.state.room_state import RoomState


class WriteOutcome(Enum):
    """一次抽屉行写入的四种结局。

    - `SUCCESS`：编辑层收下了这段文字。
    - `CONFLICT`：Soul App 拒了这次提交（改得太频繁）。编辑层还开着，
      编辑器会先把它收掉再返回。
    - `RENDER_FAILED`：入口 / 输入框 / 确认键找不到，或提交后的屏幕认不出来。
    - `SKIPPED`：守卫没让碰 UI（别人房间）。一个点击都没发生，因此不记账。
    """

    SUCCESS = 'success'
    CONFLICT = 'conflict'
    RENDER_FAILED = 'render_failed'
    SKIPPED = 'skipped'


@dataclass(frozen=True)
class WriteResult:
    """一次写入的结果：结局 + 人读得懂的原因 + 写进去的那段文字。

    Attributes:
        outcome: 四种结局之一。
        reason: 面向调用方的说明（被拒的文案、找不到的控件、跳过的原因…）。
        text: 这一次写进去的文字（成功时是它）。
    """

    outcome: WriteOutcome
    reason: Optional[str] = None
    text: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is WriteOutcome.SUCCESS


@dataclass(frozen=True)
class RowStep:
    """走到编辑层路上的一步。

    动作只有四种，认不出来时的报错文案、要不要先收掉这一层、成功之后打哪句
    日志都在这里 —— 一行抽屉的「怎么进编辑层」因此是一段**数据**，不是一段
    分支。

    Attributes:
        action: `click` / `click_at` / `wait_any_click` / `wait_marker`。
        key: 这一步要点的那个 key。
        keys: 有多个皮肤时的候选（`wait_any_click` 用）。
        y_ratio: 点元素的上缘而不是中心（`click_at` 用）。
        timeout: 等这一层出现的超时秒数。
        error: 找不到时对外的报错文案。
        close_on_missing: 找不到时先收掉这一层（底部抽屉挡住「自定义」时用）。
        missing_log: 找不到时打的告警。
        log: 成功之后打的日志（`{key}` = 命中的那个 key）。
    """

    action: str
    key: str = ''
    keys: Tuple[str, ...] = ()
    y_ratio: Optional[float] = None
    timeout: Optional[int] = None
    error: str = ''
    close_on_missing: Optional[str] = None
    missing_log: str = ''
    log: str = ''


@dataclass(frozen=True)
class RowSkin:
    """一个抽屉行的全部数据。

    一行 = 怎么走进它的编辑层 + 写什么 + 怎么判结果 + 对外长什么样。新增第四个
    抽屉字段 = 加一条这样的常量，不必再抄一遍 60~80 行 ritual。

    Attributes:
        field: 草稿库里的字段名（记账用）。
        drawer_entry_keys: 抽屉本身的入口。
        open_error: 抽屉打不开时的报错文案。
        entry_steps: 走到编辑层的那几步。
        input_key: 输入框。
        input_error: 输入框找不到时的报错文案。
        confirm_key: 确认按钮。
        confirm_error: 确认按钮找不到时的报错文案。
        no_pending_result: 没有待写入内容时的对外形状。
        cooldown_result: 冷却没到时的对外形状。
        to_result: 把结局翻译回这一行对外的 dict 形状。
        settle_attr: 提交后的静默时间取自 manager 的哪个属性（空 = 不等）。
        probe_keys: 提交后用来判结果的候选（顺序即优先级）。
        probe_outcomes: 命中哪个 key = 什么结局。
        unknown_outcome: 一个都没命中时算什么（话题是成功，房名是失败）。
        unknown_error: 认不出来时的报错文案。
        unknown_log: 认不出来时打的告警。
        conflict_error: 提交被拒时的报错文案。
        conflict_log: 提交被拒时打的告警。
        conflict_close_key: 提交被拒时收掉编辑层要点的那个 key。
        close_after_confirm: 提交成功后收掉编辑层要点的那个 key（公告）。
        write_log: 这一次写入开始时打的日志（公告：准备设置notice）。
        before_type_log: 写进输入框之前打的日志（房名：写进去的完整房名）。
        after_type_log: 写进输入框之后打的日志（公告：输入了notice内容）。
        after_confirm_log: 点完确认之后打的日志。
        after_close_log: 收掉编辑层之后打的日志。
        exception_log: UI 层抛异常时打的错误日志。
        exception_error: UI 层抛异常时的报错文案。
        compose: 写进输入框之前把文字拼成什么（房名的 `{theme}｜{title}`）。
        before_write: 走进编辑层之前要做的准备（房名：先纠偏、再判定公告）。
        after_success: 写成功之后的收尾。
        after_conflict: 提交被拒之后的收尾。
        after_failure: 这次写入「提交过了但结果认不出来」或抛异常之后的收尾。
        guard_log: 别人房间里跳过时打的日志。
        restore_guard_log: 公告恢复那条路上跳过时打的日志。
        attempt_log: 这一次写入开始时打的日志。
        flush_success_log: 记账路径上写成功时打的日志。
        failure_log: 记账路径上写失败时打的告警。
        announce: 写成功之后往公屏发的那一句。
        clear_draft_on_success: 写成功时由记账路径清草稿（房名那一行是
            `False` —— 它的清空必须与审核自愈连在一起做，顺序不能换）。
    """

    field: str
    drawer_entry_keys: Tuple[str, ...]
    open_error: str
    entry_steps: Tuple[RowStep, ...]
    input_key: str
    input_error: str
    confirm_key: str
    confirm_error: str
    no_pending_result: Dict[str, Any]
    cooldown_result: Callable[[Any], Dict[str, Any]]
    to_result: Callable[[Any, WriteResult], Dict[str, Any]]

    settle_attr: str = ''
    probe_keys: Tuple[str, ...] = ()
    probe_outcomes: Dict[str, WriteOutcome] = dc_field(default_factory=dict)
    unknown_outcome: WriteOutcome = WriteOutcome.RENDER_FAILED
    unknown_error: str = ''
    unknown_log: str = 'Unknown key: {probe}'
    conflict_error: str = ''
    conflict_log: str = ''
    conflict_close_key: Optional[str] = None
    close_after_confirm: Optional[str] = None
    write_log: str = ''
    before_type_log: str = ''
    after_type_log: str = ''
    after_confirm_log: str = ''
    after_close_log: str = ''
    exception_log: str = ''
    exception_error: str = ''

    compose: Optional[Callable[[Any, str], str]] = None
    before_write: Optional[Callable[[Any, str], None]] = None
    after_success: Optional[Callable[[Any, str], None]] = None
    after_conflict: Optional[Callable[[Any, str], None]] = None
    after_failure: Optional[Callable[[Any, str], None]] = None

    guard_log: str = ''
    restore_guard_log: str = ''

    attempt_log: str = ''
    flush_success_log: str = ''
    failure_log: str = ''
    announce: Optional[Callable[[Any, str], None]] = None
    clear_draft_on_success: bool = True


def guest_room_blocks_edit() -> bool:
    """别人房间里不许改抽屉里的字段 —— 抽屉编辑**唯一**的守卫。

    「什么算别人的房间」只有这一个定义：将来要改判定，只改这一处，不会再有
    第二个字段忘了跟。守护的是「一次点击都不许发生」—— 别人房间里我们没有
    资格改任何一行。
    """
    return RoomState.in_guest_room()


class RowEditor:
    """抽屉行编辑器：一次「打开编辑层 → 写入 → 提交 → 判结果」。

    编辑器只做物理动作。冷却预算、草稿记账与对外的返回形状都在
    `RoomProfileManager` 那一层 —— 这里唯一的对外物事是一个 `WriteOutcome`。

    Args:
        manager: `RoomProfileManager`。编辑器用它拿抽屉端口、抽屉会话与日志。
    """

    def __init__(self, manager):
        self._manager = manager

    # ------------------------------------------------------------------
    # 守卫
    # ------------------------------------------------------------------

    def guard(self, log_message: str = '') -> Optional[WriteResult]:
        """别人房间里不许动抽屉。

        Returns:
            该跳过时返回 `SKIPPED` 的结果，可以写时返回 None。
        """
        if not guest_room_blocks_edit():
            return None
        if log_message:
            self._manager.logger.info(log_message)
        return WriteResult(WriteOutcome.SKIPPED, reason='guest_room')

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def edit_row(self, skin: RowSkin, text: str) -> WriteResult:
        """把 `text` 写进 `skin` 描述的那一行。

        收尾不再盲按 `press_back()`：抽屉本身的开关由 `with_window_open` 的
        `finally` 走 `ensure_closed()` 阶梯 —— 自己没有打开抽屉就一次都不按；
        自己打开的就先点遮罩关；只有遮罩关不掉才退化为一次保底返回键。按多了
        会直接退出派对房间（spec 用户故事 #12）。

        异常一律收敛成 `RENDER_FAILED` —— 走失败的记账分支，保留草稿重试。
        """
        skipped = self.guard(skin.guard_log)
        if skipped is not None:
            return skipped

        if skin.write_log:
            self._manager.logger.info(skin.write_log.format(text=text))

        try:
            with self._manager.with_window_open(
                skin.drawer_entry_keys, skin.open_error
            ) as open_error:
                if open_error:
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED,
                        reason=open_error.get('error') or skin.open_error,
                    )

                if skin.before_write is not None:
                    skin.before_write(self._manager, text)

                failed = self._open_entry(skin)
                if failed is not None:
                    return failed

                typed = skin.compose(self._manager, text) if skin.compose else text
                if skin.before_type_log:
                    self._manager.logger.info(skin.before_type_log.format(text=typed))

                driver = self._manager.drawer_driver
                if not driver.replace_text(skin.input_key, typed):
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=skin.input_error
                    )

                if skin.after_type_log:
                    self._manager.logger.info(skin.after_type_log.format(text=typed))

                if not driver.click_element(skin.confirm_key):
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=skin.confirm_error
                    )

                if skin.after_confirm_log:
                    self._manager.logger.info(skin.after_confirm_log)

                settle = getattr(self._manager, skin.settle_attr, 0) if skin.settle_attr else 0
                if settle:
                    time.sleep(settle)

                return self._classify(skin, text)

        except Exception:
            self._manager.logger.error(
                skin.exception_log.format(traceback=traceback.format_exc())
            )
            if skin.after_failure is not None:
                skin.after_failure(self._manager, text)
            return WriteResult(
                WriteOutcome.RENDER_FAILED, reason=skin.exception_error.format(text=text)
            )

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    def _open_entry(self, skin: RowSkin) -> Optional[WriteResult]:
        """走进这一行的编辑层。找不到就返回失败结果。"""
        driver = self._manager.drawer_driver

        for step in skin.entry_steps:
            if step.action == 'click':
                if not driver.click_element(step.key):
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=step.error
                    )
                hit = step.key
            elif step.action == 'click_at':
                if not driver.click_element_at(step.key, y_ratio=step.y_ratio):
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=step.error
                    )
                hit = step.key
            elif step.action == 'wait_any_click':
                found = self._wait_for_any(step.keys, step.timeout)
                if found is None:
                    # 底部抽屉挡住了入口：先把这一层点掉，不能留在屏幕上。
                    if step.close_on_missing:
                        driver.click_element(step.close_on_missing)
                    if step.missing_log:
                        self._manager.logger.warning(step.missing_log)
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=step.error
                    )
                driver.click_element(found)
                hit = found
            elif step.action == 'wait_marker':
                if self._wait_for_any((step.key,), step.timeout) is None:
                    return WriteResult(
                        WriteOutcome.RENDER_FAILED, reason=step.error
                    )
                hit = step.key
            else:  # pragma: no cover - 皮肤写错了才会走到这里
                raise ValueError(f'unknown row step action: {step.action!r}')

            if step.log:
                self._manager.logger.info(step.log.format(key=hit))

        return None

    def _wait_for_any(self, keys: Tuple[str, ...], timeout: Optional[int]):
        driver = self._manager.drawer_driver
        if timeout is None:
            return driver.wait_for_any(keys)
        return driver.wait_for_any(keys, timeout=timeout)

    def _classify(self, skin: RowSkin, text: str) -> WriteResult:
        """提交之后：这一行的屏幕长什么样，决定了这次写入的结局。"""
        driver = self._manager.drawer_driver

        if not skin.probe_keys:
            # 没有探测的行（公告）：点完确认就收尾。
            outcome = WriteResult(WriteOutcome.SUCCESS, text=text)
        else:
            probe = driver.wait_for_any(skin.probe_keys)
            kind = skin.probe_outcomes.get(probe, skin.unknown_outcome)
            if kind is WriteOutcome.CONFLICT:
                # 提交被拒（改得太频繁）：编辑层还开着，先把它收起，别留在屏幕上。
                self._manager.logger.warning(skin.conflict_log)
                if skin.conflict_close_key:
                    driver.click_element(skin.conflict_close_key)
                if skin.after_conflict is not None:
                    skin.after_conflict(self._manager, text)
                return WriteResult(WriteOutcome.CONFLICT, reason=skin.conflict_error)
            if kind is WriteOutcome.SUCCESS:
                outcome = WriteResult(WriteOutcome.SUCCESS, text=text)
            else:
                self._manager.logger.warning(skin.unknown_log.format(probe=probe))
                if skin.after_failure is not None:
                    skin.after_failure(self._manager, text)
                outcome = WriteResult(
                    WriteOutcome.RENDER_FAILED, reason=skin.unknown_error
                )

        if skin.close_after_confirm:
            driver.click_element(skin.close_after_confirm)
            if skin.after_close_log:
                self._manager.logger.info(skin.after_close_log)

        if outcome.outcome is WriteOutcome.SUCCESS and skin.after_success is not None:
            skin.after_success(self._manager, text)

        return outcome
