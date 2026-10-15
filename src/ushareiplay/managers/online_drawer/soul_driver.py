"""生产适配器：把 `SoulHandler` 的 Appium 细节包成在线用户抽屉端口。

这里的每一步都是既有在线名单抓取已经做过的那一步，不是重新设计的交互：

- 打开是 `try_find_element('user_count')` + `click()`（旧
  `OnlineListScraper._scrape_online_user_names` 的原样两步）；
- 关闭是按 `online_users_close` -> `close_button` 顺序点 `ivClose`
  （旧 `_close_online_users_dialog` 的第一段，`#414` 之后已不再当抽屉点遮罩）；
- 滑动是在容器 `location`/`size` 算出的坐标里从 0.75 高度滑到 0.30 高度，
  算不出时回落到既有的固定坐标；时长 800ms，是旧实现为避免惯性飞滚特意调慢过的值。

刻意**不移植**旧实现里的 `press_back` 与遮罩点击两段兜底：盲按返回会误退出派对
房间（spec #426 问题陈述 #1），而 `ivClose` 已经是确定可用的手势。旧路径保持原样
不动，等 #440 收口时统一退役。
"""

import asyncio
import re
from typing import Optional

from ushareiplay.managers.online_drawer.driver import (
    CLOSE_KEYS,
    DEFAULT_SCROLL_DURATION_MS,
    DEFAULT_SETTLE_TIMEOUT,
    END_OF_LIST_KEY,
    ENTRY_KEY,
    ONLINE_CONTAINER_KEY,
    POST_SCROLL_SETTLE_SECONDS,
    ROW_CONTAINER_KEY,
    ROW_FOLLOW_STATE_KEY,
    ROW_NAME_KEY,
    SETTLE_SECONDS,
    MemberRow,
    OnlineDrawerDriverPort,
)


class SoulOnlineDrawerDriver(OnlineDrawerDriverPort):
    """驱动真实 Soul App 在线用户抽屉的生产适配器。

    Args:
        handler: 注入的 `SoulHandler`。`None` 时所有动作都以「App 不可用」的
            方式失败，而不是抛 AttributeError。
    """

    def __init__(self, handler=None):
        self._handler = handler

    async def is_open(self) -> bool:
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False
        try:
            return bool(finder.try_find_element(ONLINE_CONTAINER_KEY, log=False))
        except Exception:
            return False

    async def open(self, *, error_message: str) -> dict:
        handler = self._handler
        if handler is None:
            return {'error': error_message}
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return {'error': error_message}

        entry = finder.try_find_element(ENTRY_KEY, log=False)
        if not entry:
            return {'error': error_message}
        try:
            entry.click()
        except Exception as e:
            self._log_warning(f"点击 {ENTRY_KEY} 失败: {e}")
            return {'error': error_message}
        return {}

    async def close(self) -> bool:
        """按顺序点专门的 `ivClose` 关闭按钮；两个都点不到返回 False。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False

        for key in CLOSE_KEYS:
            try:
                close_btn = None
                if hasattr(finder, "wait_for_element_clickable"):
                    close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn and hasattr(finder, "try_find_element"):
                    close_btn = finder.try_find_element(key, log=False)

                if close_btn:
                    close_btn.click()
                    if hasattr(finder, "wait_for_element_disappear"):
                        finder.wait_for_element_disappear(
                            key, timeout=2.0, poll_frequency=0.1
                        )
                    return True
            except Exception as e:
                self._log_warning(f"查找/点击关闭按钮 {key} 出错: {e}")

        return False

    async def wait_for_settle(self, *, timeout: int = DEFAULT_SETTLE_TIMEOUT) -> bool:
        """等容器出现，并留出它渲染行内容所需的静默。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False

        container = finder.wait_for_element(ONLINE_CONTAINER_KEY, timeout=timeout)
        if not container:
            return False
        # 容器在 dump 里不等于行已经渲染出来，紧接着读会读到空的列表。
        await asyncio.sleep(SETTLE_SECONDS)
        return True

    async def scroll_container(
        self, *, duration_ms: int = DEFAULT_SCROLL_DURATION_MS
    ) -> bool:
        """在容器内手指上滑，列表向下滚一页；滑完等列表停稳。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        gesture = getattr(handler, "gesture_handler", None)
        if finder is None or gesture is None or not hasattr(gesture, "swipe"):
            return False

        container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
        swipe_x, start_y, end_y = self._swipe_geometry(container)

        try:
            if swipe_x is not None:
                ok = gesture.swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=duration_ms)
            else:
                # 容器坐标读不出来时的固定回落位，与旧实现逐字一致。
                ok = gesture.swipe(500, 1500, 500, 900, duration_ms)
            if not ok:
                self._log_warning("在线用户列表滑动失败")
                return False
        except Exception as e:
            self._log_warning(f"滑动在线用户列表时出错: {e}")
            return False

        # 滑完必须等 RecyclerView 停稳，否则下一步读到的是滑动途中的画面。
        await asyncio.sleep(POST_SCROLL_SETTLE_SECONDS)
        return True

    async def find_member_row(self, visible_username: str) -> Optional[MemberRow]:
        handler = self._handler
        if handler is None:
            return None
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return None

        container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
        if not container:
            return None

        for row in finder.find_child_elements(container, ROW_CONTAINER_KEY):
            try:
                name_elem = finder.find_child_element(row, ROW_NAME_KEY)
                if not name_elem:
                    continue
                # 只按 UI 上显示的昵称匹配：canonical 名在这里永远不相等。
                if (name_elem.text or '') != visible_username:
                    continue
                follow_elem = finder.find_child_element(
                    row, ROW_FOLLOW_STATE_KEY, log_failure=False
                )
                return MemberRow(
                    visible_name=name_elem.text,
                    follow_state=follow_elem.text if follow_elem else None,
                )
            except Exception:
                # 单行读坏不影响继续找下一行（滑动过程中行会失效是常态）。
                continue

        return None

    async def read_online_count(self) -> Optional[int]:
        """读「N 人在线」控件里第一段数字。

        解析留在这里而不是引擎：`6人在线` / `在线 10 人` 这些文案是 App 的事，引擎
        只该拿到一个 int 或 None。旧实现在 `OnlineListScraper` 里用同一个正则解析，
        这里只是把它挪到它该在的层。
        """
        finder = self._finder()
        if finder is None:
            return None
        try:
            entry = finder.try_find_element(ENTRY_KEY, log=False)
            if not entry:
                return None
            text = getattr(entry, "text", None)
            if not text:
                return None
            match = re.search(r'(\d+)', text)
            if not match:
                return None
            return int(match.group(1))
        except Exception:
            # 人数只是对账的期望值，读不到不该让整次抓取失败。
            return None

    async def visible_member_rows(self) -> list:
        """整页已渲染的行，一次读回昵称与关注关系。

        「翻页判据是这一页有没有带来新的人」，所以整页读数是一次语义上的读取；
        逐行问端口会把同一页 dump 五十次，正是这段旧代码当初踩的坑。
        """
        finder = self._finder()
        if finder is None:
            return []
        try:
            container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
            if not container:
                return []

            rows = []
            for row in finder.find_child_elements(container, ROW_CONTAINER_KEY):
                try:
                    name_elem = finder.find_child_element(row, ROW_NAME_KEY)
                    if not name_elem:
                        continue
                    visible_name = name_elem.text
                    if not visible_name:
                        continue
                    follow_elem = finder.find_child_element(
                        row, ROW_FOLLOW_STATE_KEY, log_failure=False
                    )
                    rows.append(
                        MemberRow(
                            visible_name=visible_name,
                            follow_state=follow_elem.text if follow_elem else None,
                        )
                    )
                except Exception:
                    # 单行读坏跳过整行，不影响这一页剩下的行（滚动途中失效是常态）。
                    continue
            return rows
        except Exception:
            return []

    async def is_at_end(self) -> bool:
        """`no_more_data` 提示在不在**且显示着**。"""
        finder = self._finder()
        if finder is None:
            return False
        try:
            hint = finder.try_find_element(END_OF_LIST_KEY, log=False)
            if not hint:
                return False
            return bool(hint.is_displayed())
        except Exception:
            return False

    def _finder(self):
        """handler / element_finder 任一缺席都退化成「App 不可用」。"""
        handler = self._handler
        if handler is None:
            return None
        return getattr(handler, "element_finder", None)

    def _swipe_geometry(self, container):
        """容器内滑动的起止坐标：手指从 0.75 高度划到 0.30 高度。

        算不出来时返回三个 None，由调用方回落到固定坐标 —— 与旧实现相同的处理，
        免得一次坐标读不到就彻底不能滚。
        """
        try:
            loc = container.location
            size = container.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            return (
                left + int(width * 0.5),
                top + int(height * 0.75),
                top + int(height * 0.30),
            )
        except Exception:
            return None, None, None

    def _log_warning(self, message: str) -> None:
        handler = self._handler
        logger = getattr(handler, "logger", None) if handler is not None else None
        if logger is not None:
            logger.warning(f"[online_drawer] {message}")
