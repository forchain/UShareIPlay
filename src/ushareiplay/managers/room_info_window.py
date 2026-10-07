"""房间信息窗口 —— 过渡期门面，真实实现在 `RoomProfileManager`。

同一个抽屉承载四类字段：房间标题、房间话题、派对公告、派对类型与推荐分发。
原先它有四个「打开者」各自复制一遍打开 ritual，关闭则靠 `PartyManager` 的
`finally` 兜底，而「在窗口里必须按什么顺序同步」只写在注释里。

现在只有一个模块知道窗口什么时候开着：

    with RoomProfileManager.instance().with_window_open() as open_error:
        if open_error:
            return open_error
        <每个 manager 只做自己字段的编辑>

    results = RoomProfileManager.instance().audit_and_repair()   # 一次性全量检查与修正

**本模块现在只是一层转发。** 抽屉的全部实现（探测、打开、正规关窗、保底返回、
窗口内的顺序、全量审计）都在 `ushareiplay.managers.room_profile.manager` 里，
通过抽屉 UI 端口驱动。保留这里是为了让既有调用点（`recommendation_manager`、
`party_manager`、`commands/recommend.py`）一行不改地继续工作：

- #392-#393 把这些调用点逐个迁到 `RoomProfileManager`
- #394 删掉本文件

因此本门面必须**透明**：所有公开方法原样转发，包括既有调用点依赖的
`error_message` 文案与「只关自己打开的那一次」语义。
`RoomInfoWindowAuditor` 的职责（全量审计 + 待重试标记）早已并入
`audit_and_repair()` / `process_pending_retry()`，该模块已删除。
"""

import logging
from contextlib import contextmanager
from typing import Dict, Iterator, Optional, Sequence

from ushareiplay.core.singleton import Singleton
from ushareiplay.managers.room_profile.driver import (
    DEFAULT_ENTRY_KEYS,
    DIALOG_KEYS,
)
from ushareiplay.managers.room_profile.manager import RoomProfileManager
from ushareiplay.managers.room_profile.soul_drawer import SoulDrawerDriver

__all__ = [
    "DEFAULT_ENTRY_KEYS",
    "DIALOG_KEYS",
    "RoomInfoWindow",
]


class RoomInfoWindow(Singleton):
    """抽屉会话的转发门面。真正的所有者是 `RoomProfileManager`（#394 删除本类）。"""

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, 'logger', None) or logging.getLogger("RoomInfoWindow")
        return self._logger

    @property
    def _profile(self) -> Optional[RoomProfileManager]:
        """真实实现所在的单例；组合根还没注册它时为 None。"""
        if not RoomProfileManager.is_initialized():
            return None
        profile = RoomProfileManager.instance()
        if self._handler is not None and profile.handler is not self._handler:
            # 过渡期：既有调用点（与既有测试）把 handler 注入到本窗口上，
            # 真实实现从 RoomProfileManager 读同一个 handler 和它的生产端口。
            # #394 之后两个 handler 必然是同一个对象，这段分支随之消失。
            profile.adopt_handler(self._handler, SoulDrawerDriver(self._handler))
        return profile

    @property
    def pending_audit_retry(self) -> bool:
        profile = self._profile
        return profile.pending_audit_retry if profile is not None else False

    @pending_audit_retry.setter
    def pending_audit_retry(self, value) -> None:
        profile = self._profile
        if profile is not None:
            profile.pending_audit_retry = value

    @property
    def last_audit_results(self) -> Dict:
        profile = self._profile
        return profile.last_audit_results if profile is not None else {}

    @last_audit_results.setter
    def last_audit_results(self, value) -> None:
        profile = self._profile
        if profile is not None:
            profile.last_audit_results = value

    # ------------------------------------------------------------------
    # 生命周期（转发）
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """窗口（抽屉）当前是否开着。"""
        profile = self._profile
        return profile.is_open() if profile is not None else False

    def ensure_open(
        self,
        entry_keys: Optional[Sequence[str]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[dict]:
        """确保窗口已打开；已开着则直接返回。

        Args:
            entry_keys: 打开入口，默认 chat_room_title -> room_topic
            error_message: 打不开时返回给调用方的文案。调用方原样传入自己面向
                           用户的报错文本，以免统一入口后改变聊天气泡里的报错。

        Returns:
            error dict 表示打不开，None 表示窗口可用。
        """
        profile = self._profile
        if profile is None:
            return {'error': error_message or 'Soul handler is not available'}
        return profile.ensure_open(entry_keys, error_message)

    def ensure_closed(self) -> None:
        """确保窗口已关闭，恢复至主房间界面。"""
        profile = self._profile
        if profile is not None:
            profile.ensure_closed()

    @contextmanager
    def with_window_open(self, entry_keys: Optional[Sequence[str]] = None) -> Iterator[Optional[dict]]:
        """窗口开着的上下文：需要时才打开，且只关掉自己打开的那一次。"""
        profile = self._profile
        if profile is None:
            yield {'error': 'Soul handler is not available'}
            return
        with profile.with_window_open(entry_keys) as open_error:
            yield open_error

    def close_with_back(self) -> None:
        """关掉编辑层后回到主界面：先按一次返回，必要时再按一次。"""
        profile = self._profile
        if profile is not None:
            profile.close_with_back()

    # ------------------------------------------------------------------
    # 窗口内的顺序与全量审计（转发）
    # ------------------------------------------------------------------

    def sync_while_open(self, wait: bool = False) -> Dict:
        """窗口已打开时的「先纠偏再编辑」顺序。"""
        profile = self._profile
        return profile.sync_while_open(wait) if profile is not None else {}

    def audit_and_repair(self) -> Dict:
        """打开窗口，一次性顺序完成四类检查与修正，最后统一关窗。"""
        profile = self._profile
        if profile is None:
            return {'open': {'error': 'Soul handler is not available'}}
        return profile.audit_and_repair()

    def process_pending_retry(self) -> Dict:
        """补救机制：上次审计有未完成项时，重新打开窗口执行一次全量修正。"""
        profile = self._profile
        if profile is None:
            return {'skipped': 'No pending audit retry'}
        return profile.process_pending_retry()
