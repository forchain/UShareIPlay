import asyncio
import traceback

from ushareiplay.core.singleton import Singleton


class OnlineListScraper(Singleton):
    """从 Soul App 在线用户列表 UI 抓取当前在线用户。"""

    def __init__(self):
        self._logger = None
        self._handler = None

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._logger = SoulHandler.instance().logger
        return self._logger

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    async def refresh_online_users(self):
        """人数变化时，从在线用户列表 UI 刷新在线用户集合，并更新用户等级。"""
        try:
            from ushareiplay.state.room_state import RoomState
            from ushareiplay.state.presence_tracker import PresenceTracker
            from ushareiplay.dal.user_dao import UserDAO

            target_count = RoomState.instance().user_count

            # 打开在线用户列表
            user_count_elem = self.handler.element_finder.try_find_element('user_count', log=False)
            if not user_count_elem:
                return
            user_count_elem.click()
            self.logger.info("Clicked user count element")

            online_container = self.handler.element_finder.wait_for_element('online_users')
            if not online_container:
                self.logger.error("Online users container not found")
                return

            all_online_user_names = set()
            prev_size = 0
            no_new_rounds = 0
            max_no_new_rounds = 2
            max_swipes = 50

            # 预计算容器内滑动坐标：手指向上滑（列表向上滚动）
            try:
                loc = online_container.location
                size = online_container.size
                left = int(loc["x"])
                top = int(loc["y"])
                width = int(size["width"])
                height = int(size["height"])

                swipe_x = left + int(width * 0.5)
                start_y = top + int(height * 0.8)
                end_y = top + int(height * 0.2)
            except Exception:
                self.logger.warning("Failed to compute container swipe coordinates, fallback to default swipe")
                swipe_x = None
                start_y = None
                end_y = None

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
                        ok = self.handler.gesture_handler.swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=400)
                        if not ok:
                            self.logger.warning("Swipe failed, stop scrolling online users.")
                            break
                    else:
                        self.handler.gesture_handler.swipe(500, 1500, 500, 800, 600)
                except Exception as e:
                    self.logger.error(f"Error during swipe operation: {str(e)}")
                    break

                try:
                    await asyncio.sleep(0.35)
                except Exception:
                    pass

            PresenceTracker.instance().update_online_users(list(all_online_user_names))

            bottom_drawer = self.handler.element_finder.wait_for_element('bottom_drawer')
            if bottom_drawer:
                self.logger.info('Hide online users dialog')
                self.handler.gesture_handler.click_element_at(bottom_drawer, 0.5, -0.1)
        except Exception:
            self.logger.error(f"Error refreshing online users: {traceback.format_exc()}")
