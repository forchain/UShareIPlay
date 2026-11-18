"""在线名单抓取（Soul 在线用户抽屉）。

全部物理动作都在 `OnlineDrawer.drawer_session` 里进出抽屉（#432）。本适配器
只保留**唯一一件事**：把列表一页一页读全，以及决定什么时候停。翻页判据是循环
决策，抽屉管理器只负责把「此刻屏幕上有什么」如实读回来。

三条要守住的约定：

1. **人数在打开之前读**：抽屉一旦盖上来，房间里「N 人在线」那个控件就被挡住了。
2. **一次抓取一个会话**：旧实现每次抓取自己开关抽屉，因此人数对不上时的重试拿到
   的是一张**从第一页开始**的列表。列表没法往回滚，这是重试唯一可能奏效的前提。
3. **UI 独占锁留在最外层**：`refresh_online_users` 持锁跨越两次抓取（含中间的 0.4s
   间隔），`drawer_session` 在里面可重入地嵌套。
"""

import asyncio
import logging
import traceback
from typing import Callable, Optional, Set, Tuple

from ushareiplay.modules.room.ports import OnlineListSource, PresenceQuery
from ushareiplay.modules.user.ports import UserRepository

#: 最多翻多少页。上限存在的理由是「别把一次刷新变成无上限轮询」。
MAX_SWIPES = 50

#: 连续多少轮没带来新面孔就认为翻不动了。这条是兜底：到底提示读不到时靠它收尾。
MAX_NO_NEW_ROUNDS = 2

#: 关注关系文案 -> 等级。顺序即优先级：「密友」文案里同时带「我关注的」字样，
#: 先判密友才不会把人降级。
FOLLOW_STATE_LEVELS = (("密友", 3), ("我关注的", 2), ("关注了我", 1))


class SoulOnlineListSource(OnlineListSource):
    """从 Soul App 在线用户抽屉抓取当前在线用户。"""

    def __init__(
        self,
        *,
        drawer,
        users: UserRepository,
        presence: PresenceQuery,
        room_state,
        ui_session: Callable[[str], object],
        logger: Optional[logging.Logger] = None,
    ):
        self._drawer = drawer
        self._users = users
        self._presence = presence
        self._room_state = room_state
        self._ui_session = ui_session
        self._logger = logger

    @property
    def logger(self):
        if self._logger is None:
            self._logger = logging.getLogger("ushareiplay.state.online_list_scraper")
        return self._logger

    async def _scrape_online_user_names(
        self, target_count: Optional[int] = None
    ) -> Tuple[Optional[Set[str]], Optional[int]]:
        """在一个抽屉会话里抓全在线用户，返回 (用户名集合, 探测到的人数)。"""
        drawer = self._drawer
        driver = drawer.driver

        # 人数必须在抽屉打开**之前**读：抽屉一盖就挡住这个控件了。
        detected_count = await driver.read_online_count()

        async with drawer.drawer_session("state:scrape_online_users") as open_error:
            if open_error:
                return None, detected_count
            return await self._collect_online_user_names(driver, target_count), detected_count

    async def _collect_online_user_names(self, driver, target_count: Optional[int]) -> Set[str]:
        """把已经打开的抽屉一页一页读全，直到某个终止条件成立。"""
        all_online_user_names = set()
        prev_size = 0
        no_new_rounds = 0

        for swipe_idx in range(MAX_SWIPES + 1):
            for row in await driver.visible_member_rows():
                # 仍用用户名判断唯一性；只对新出现的用户处理关注状态/等级
                if not row.visible_name or row.visible_name in all_online_user_names:
                    continue
                all_online_user_names.add(row.visible_name)
                try:
                    await self._record_new_user(row.visible_name, row.follow_state)
                except Exception:
                    # 单个用户建档/定级失败不该中断整页抓取，人名本身已经收下了。
                    continue

            if await driver.is_at_end():
                self.logger.info("Detected no_more_data, stop scrolling online users.")
                break

            if target_count is not None and len(all_online_user_names) >= target_count:
                self.logger.info(f"Collected {len(all_online_user_names)}/{target_count} users, stop scrolling.")
                break

            if len(all_online_user_names) == prev_size:
                no_new_rounds += 1
            else:
                no_new_rounds = 0
                prev_size = len(all_online_user_names)
            if no_new_rounds >= MAX_NO_NEW_ROUNDS:
                self.logger.info(f"No new users found for {no_new_rounds} rounds, stop scrolling.")
                break

            if swipe_idx >= MAX_SWIPES:
                self.logger.info("Reached max_swipes, stop scrolling online users.")
                break

            if not await driver.scroll_container():
                self.logger.warning("Swipe failed, stop scrolling online users.")
                break

        return all_online_user_names

    async def _record_new_user(self, visible_name: str, follow_state: Optional[str]) -> None:
        """按关注关系给新面孔定级；没有关注关系就先在 DB 里建档。"""
        if not follow_state:
            await self._users.get_or_create(visible_name)
            return

        for marker, level in FOLLOW_STATE_LEVELS:
            if marker in follow_state:
                await self._users.update_level_if_lower(visible_name, level)
                return
        # 关注关系文案三种都不匹配：不猜等级，也不建档（与旧实现同样处理）。

    async def refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        """人数变化时，从在线用户列表 UI 刷新在线用户集合，并更新用户等级。"""
        # 锁在**两次抓取之外**持有：人数对不上时的间隔期也不能放锁。
        async with self._ui_session("event:refresh_online_users"):
            return await self._do_refresh_online_users(target_count)

    async def _do_refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        try:
            expected_count = target_count
            if expected_count is None:
                expected_count = self._room_state.user_count

            # 第 1 次抓取
            user_names, detected_count = await self._scrape_online_user_names(expected_count)
            if user_names is None:
                return False

            if expected_count is None:
                expected_count = detected_count

            # 比对在线列表人数与房间显示的在线人数
            if expected_count is not None and len(user_names) != expected_count:
                self.logger.warning(
                    f"Online users count mismatch: scraped {len(user_names)}, "
                    f"expected {expected_count}. Retrying once..."
                )
                try:
                    await asyncio.sleep(0.4)
                except Exception:
                    pass

                # 重试第 2 次抓取：新会话、新列表 —— 上一张已经滑到底，回不去了。
                user_names_retry, detected_count_retry = await self._scrape_online_user_names(expected_count)
                if user_names_retry is not None:
                    user_names = user_names_retry
                    if detected_count_retry is not None:
                        expected_count = detected_count_retry

                if expected_count is not None and len(user_names) != expected_count:
                    self.logger.warning(
                        f"Online users count still mismatched after retry: scraped {len(user_names)}, "
                        f"expected {expected_count}. Proceeding with best-effort list."
                    )

            self._presence.update_online_users(list(user_names))
            return True
        except Exception:
            self.logger.error(f"Error refreshing online users: {traceback.format_exc()}")
            return False
