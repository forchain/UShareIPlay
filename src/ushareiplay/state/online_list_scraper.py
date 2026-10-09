import asyncio
import logging
import re
import traceback
from typing import Optional, Set, Tuple

from ushareiplay.core.singleton import Singleton
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.state.presence_tracker import PresenceTracker
from ushareiplay.state.room_state import RoomState


class OnlineListScraper(Singleton):
    """从 Soul App 在线用户列表 UI 抓取当前在线用户。"""

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def logger(self):
        """获取 logger 实例"""
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("ushareiplay.state.online_list_scraper")
        return self._logger

    @property
    def handler(self):
        return self._handler

    def _close_online_users_dialog(self) -> None:
        """关闭在线用户列表弹窗。

        优先点击专门的关闭按钮（ivClose），避免按抽屉遮罩点击导致无法关闭；
        若未找到关闭按钮，使用 press_back 作为第一保底；
        最后保留旧版抽屉遮罩点击作为兜底。
        """
        finder = getattr(self.handler, "element_finder", None)
        if finder:
            for key in ('online_users_close', 'close_button'):
                try:
                    close_btn = None
                    if hasattr(finder, "wait_for_element_clickable"):
                        close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                    if not close_btn and hasattr(finder, "try_find_element"):
                        close_btn = finder.try_find_element(key, log=False)

                    if close_btn:
                        self.logger.info(f"Close online users dialog via close button ({key})")
                        close_btn.click()
                        if hasattr(finder, "wait_for_element_disappear"):
                            finder.wait_for_element_disappear(key, timeout=2.0, poll_frequency=0.1)
                        return
                except Exception as e:
                    self.logger.debug(f"Error checking/clicking close button {key}: {e}")

        try:
            # 优先使用 press_back 兜底（Soul 对所有弹窗均响应 back 键退出）
            key_actions = getattr(self.handler, "key_actions", None)
            if key_actions and hasattr(key_actions, "press_back"):
                self.logger.info("Close online users dialog via press_back")
                key_actions.press_back()
                return
        except Exception as e:
            self.logger.warning(f"Error pressing back to close online users dialog: {e}")

        try:
            # 兼容旧逻辑：点击抽屉上方遮罩
            if finder and hasattr(finder, "try_find_element"):
                bottom_drawer = finder.try_find_element('bottom_drawer', log=False)
                if bottom_drawer:
                    self.logger.info('Hide online users dialog via drawer mask click')
                    self.handler.gesture_handler.click_element_at(bottom_drawer, 0.5, -0.1)
        except Exception as e:
            self.logger.warning(f"Failed to hide online users dialog via drawer mask: {e}")

    async def _scrape_online_user_names(
        self, target_count: Optional[int] = None
    ) -> Tuple[Optional[Set[str]], Optional[int]]:
        """打开在线用户列表抽屉，抓取在线用户并返回 (用户名集合, 探测到的人数)。

        如果在打开前从 user_count 文本中解析出人数，返回为 detected_count。
        """
        user_count_elem = self.handler.element_finder.try_find_element('user_count', log=False)
        if not user_count_elem:
            self.logger.warning("user_count element not found, cannot refresh online users")
            return None, None

        detected_count = None
        try:
            text = getattr(user_count_elem, "text", None)
            if text:
                match = re.search(r'(\d+)', text)
                if match:
                    detected_count = int(match.group(1))
        except Exception:
            pass

        try:
            user_count_elem.click()
        except Exception as e:
            self.logger.warning(f"Failed to click user_count element: {str(e)}")
            return None, detected_count

        self.logger.info("Clicked user count element")

        online_container = self.handler.element_finder.wait_for_element('online_users')
        if not online_container:
            self.logger.error("Online users container not found")
            self._close_online_users_dialog()
            return None, detected_count

        try:
            await asyncio.sleep(0.4)
        except Exception:
            pass

        all_online_user_names = set()
        prev_size = 0
        no_new_rounds = 0
        max_no_new_rounds = 2
        max_swipes = 50

        # 预计算容器内滑动坐标：手指向上滑（列表向上滚动）
        # 适当缩短滑动距离、放慢滑动时间，避免列表惯性飞滚跳过未渲染项
        try:
            loc = online_container.location
            size = online_container.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            swipe_x = left + int(width * 0.5)
            start_y = top + int(height * 0.75)
            end_y = top + int(height * 0.30)
        except Exception:
            self.logger.warning("Failed to compute container swipe coordinates, fallback to default swipe")
            swipe_x = None
            start_y = None
            end_y = None

        try:
            for swipe_idx in range(max_swipes + 1):
                visible_containers = self.handler.element_finder.find_child_elements(online_container, 'user_container')
                if visible_containers:
                    for container in visible_containers:
                        try:
                            user_elem = self.handler.element_finder.find_child_element(container, 'online_user')
                            if not user_elem:
                                continue
                            username = user_elem.text
                            if not username:
                                continue

                            # 仍用用户名判断唯一性；只对新出现的用户处理关注状态/等级
                            if username in all_online_user_names:
                                continue
                            all_online_user_names.add(username)

                            follow_state_elem = self.handler.element_finder.find_child_element(container, 'follow_state')
                            follow_state = follow_state_elem.text if follow_state_elem else None

                            if follow_state:
                                if "密友" in follow_state:
                                    await UserDAO.update_level_if_lower(username, 3)
                                elif "我关注的" in follow_state:
                                    await UserDAO.update_level_if_lower(username, 2)
                                elif "关注了我" in follow_state:
                                    await UserDAO.update_level_if_lower(username, 1)
                            else:
                                await UserDAO.get_or_create(username)
                        except Exception:
                            continue

                # 停止条件 1：到底提示出现
                try:
                    no_more = self.handler.element_finder.try_find_element('no_more_data', log=False)
                    if no_more and no_more.is_displayed():
                        self.logger.info("Detected no_more_data, stop scrolling online users.")
                        break
                except Exception:
                    pass

                # 停止条件 2：已收集人数达到目标人数（更快结束）
                if target_count is not None and len(all_online_user_names) >= target_count:
                    self.logger.info(f"Collected {len(all_online_user_names)}/{target_count} users, stop scrolling.")
                    break

                # 停止条件 3：连续多轮无新增（兜底）
                if len(all_online_user_names) == prev_size:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0
                    prev_size = len(all_online_user_names)
                if no_new_rounds >= max_no_new_rounds:
                    self.logger.info(f"No new users found for {no_new_rounds} rounds, stop scrolling.")
                    break

                if swipe_idx >= max_swipes:
                    self.logger.info("Reached max_swipes, stop scrolling online users.")
                    break

                try:
                    if swipe_x is not None:
                        # 降低翻页速度：持续时间从 400ms 提高到 800ms
                        ok = self.handler.gesture_handler.swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=800)
                        if not ok:
                            self.logger.warning("Swipe failed, stop scrolling online users.")
                            break
                    else:
                        self.handler.gesture_handler.swipe(500, 1500, 500, 900, 800)
                except Exception as e:
                    self.logger.error(f"Error during swipe operation: {str(e)}")
                    break

                try:
                    # 延长翻页后等待时间，确保 RecyclerView 停稳并完成视图渲染
                    await asyncio.sleep(0.6)
                except Exception:
                    pass
        finally:
            self._close_online_users_dialog()

        return all_online_user_names, detected_count

    async def refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        """人数变化时，从在线用户列表 UI 刷新在线用户集合，并更新用户等级。"""
        controller = getattr(self.handler, "controller", None)
        if controller and hasattr(controller, "ui_session"):
            session = controller.ui_session("event:refresh_online_users")
            if hasattr(session, "__aenter__"):
                async with session:
                    return await self._do_refresh_online_users(target_count)
        return await self._do_refresh_online_users(target_count)

    async def _do_refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        try:
            expected_count = target_count
            if expected_count is None:
                expected_count = RoomState.instance().user_count

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

                # 重试第 2 次抓取
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

            PresenceTracker.instance().update_online_users(list(user_names))
            return True
        except Exception:
            self.logger.error(f"Error refreshing online users: {traceback.format_exc()}")
            return False
