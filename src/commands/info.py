import traceback

from ..core.base_command import BaseCommand
import re


def create_command(controller):
    info_command = InfoCommand(controller)
    controller.info_command = info_command
    return info_command


command = None


class InfoCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler
        self.last_user_count = None

    async def process(self, message_info, parameters):
        # 从缓存获取播放信息
        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()
        result = info_manager.get_playback_info_cache()
        
        # 如果缓存未初始化，使用默认值
        if result is None:
            result = {
                'song': 'Unknown',
                'singer': 'Unknown',
                'album': 'Unknown',
                'state': None
            }
        
        # 追加播放器信息和在线用户列表
        result['player'] = info_manager.player_name
        
        online_users = info_manager.get_online_users()
        if online_users:
            result['online_users'] = f"在线用户 ({len(online_users)}人): {', '.join(sorted(online_users))}"
        else:
            result['online_users'] = "在线用户列表暂未更新"
        
        # 追加派对时长信息
        party_duration = info_manager.get_party_duration_info()
        result['party_duration'] = party_duration if party_duration else ""
        
        # 追加当前歌单信息
        playlist_info = info_manager.get_playlist_info()
        if playlist_info and playlist_info.get('name'):
            playlist_type_map = {
                'singer': '歌手',
                'playlist': '歌单', 
                'album': '专辑',
                'radio': '电台',
                'favorites': '收藏',
                'radar': '雷达',
                'unknown': '未知'
            }
            ptype = playlist_type_map.get(playlist_info['type'], playlist_info['type'])
            result['current_playlist'] = f"[{ptype}] {playlist_info['name']} (by {result['player']})"
        else:
            result['current_playlist'] = "暂无活跃歌单"
        
        return result

    def update(self):
        """Check and log user count changes, and update playback info"""
        try:
            # Update info manager (handles playback info changes, quality check, etc.)
            from ..managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            info_manager.update()
            
            # Check and log user count changes
            user_count_elem = self.handler.try_find_element_plus('user_count', log=False)
            if not user_count_elem:
                return

            current_count = user_count_elem.text
            if current_count == self.last_user_count:
                return

            self.handler.logger.info(f"User count changed: {self.last_user_count} -> {current_count}")
            self.last_user_count = current_count

            user_count_elem.click()
            self.handler.logger.info("Clicked user count element")

            # 等待在线用户列表容器出现，然后在容器内循环上滑直到 no_more_data
            online_container = self.handler.wait_for_element_plus('online_users')
            if not online_container:
                self.handler.logger.error("Online users container not found")
                return

            # 解析目标人数（例如 "6人"）
            target_count = None
            try:
                m = re.search(r"(\d+)", current_count or "")
                target_count = int(m.group(1)) if m else None
            except Exception:
                target_count = None

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
                self.handler.logger.warning("Failed to compute container swipe coordinates, fallback to default swipe")
                swipe_x = None
                start_y = None
                end_y = None

            for swipe_idx in range(max_swipes + 1):
                # 采集当前可见用户（容器内）
                visible_users = self.handler.find_child_elements_plus(online_container, 'online_user')
                if visible_users:
                    for user in visible_users:
                        try:
                            user_text = user.text
                            if user_text:
                                all_online_user_names.add(user_text)
                        except Exception:
                            continue

                # 停止条件 1：到底提示出现
                try:
                    no_more = self.handler.try_find_element_plus('no_more_data', log=False)
                    if no_more and no_more.is_displayed():
                        self.handler.logger.info("Detected no_more_data, stop scrolling online users.")
                        break
                except Exception:
                    # ignore detection errors, continue scrolling with other stop conditions
                    pass

                # 停止条件 2：已收集人数达到目标人数（更快结束）
                if target_count is not None and len(all_online_user_names) >= target_count:
                    self.handler.logger.info(
                        f"Collected {len(all_online_user_names)}/{target_count} users, stop scrolling."
                    )
                    break

                # 停止条件 3：连续多轮无新增（兜底）
                if len(all_online_user_names) == prev_size:
                    no_new_rounds += 1
                else:
                    no_new_rounds = 0
                    prev_size = len(all_online_user_names)

                if no_new_rounds >= max_no_new_rounds:
                    self.handler.logger.info(
                        f"No new users found for {no_new_rounds} rounds, stop scrolling."
                    )
                    break

                # 最后一次循环不再滑动（max_swipes 达到）
                if swipe_idx >= max_swipes:
                    self.handler.logger.info("Reached max_swipes, stop scrolling online users.")
                    break

                # 执行一次上滑
                try:
                    if swipe_x is not None:
                        ok = self.handler._perform_swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=400)
                        if not ok:
                            self.handler.logger.warning("Swipe failed, stop scrolling online users.")
                            break
                    else:
                        # 兼容兜底：使用 driver.swipe 做一次中等幅度上滑
                        self.handler.driver.swipe(500, 1500, 500, 800, 600)
                except Exception as e:
                    self.handler.log_error(f"Error during swipe operation: {str(e)}")
                    break

                # 等待列表加载稳定
                try:
                    import time
                    time.sleep(0.35)
                except Exception:
                    pass

            # 更新在线用户列表到 InfoManager
            from ..managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            info_manager.update_online_users(list(all_online_user_names))

            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.logger.info('Hide online users dialog')
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)

        except Exception:
            self.handler.log_error(f"Error checking user count: {traceback.format_exc()}")
