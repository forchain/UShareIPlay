import traceback

from ..core.base_command import BaseCommand


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
        result = self.music_handler.get_playback_info()
        
        # 追加播放器信息和在线用户列表
        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()
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
        """Check and log user count changes"""
        try:
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

            online_user = self.handler.wait_for_element_plus('online_user')
            if online_user:
                online_users = self.handler.find_elements_plus('online_user')
                
                # 收集所有在线用户名
                all_online_user_names = set()

                # 如果在线用户超过5个，先输出前5个
                if int(current_count[:-1]) > 5:
                    self.handler.logger.info(f"Found {len(online_users)} online users, processing in batches...")

                    # 输出前5个用户
                    first_five_names = set()
                    for i, user in enumerate(online_users[:5]):
                        user_text = user.text
                        first_five_names.add(user_text)
                        all_online_user_names.add(user_text)
                        self.handler.logger.info(f"Online user {i + 1}: {user_text}")

                    # 从最后一个位置滑动到第一个位置
                    last_user = online_users[-1]
                    first_user = online_users[0]

                    # 执行滑动操作：从最后一个用户滑动到第一个用户
                    self.handler.logger.info("Sliding from last user to first user to refresh list...")

                    try:
                        # 获取最后一个用户的位置和尺寸
                        last_location = last_user.location
                        last_size = last_user.size

                        # 获取第一个用户的位置和尺寸
                        first_location = first_user.location
                        first_size = first_user.size

                        # 计算滑动起点（最后一个用户的右侧中心）
                        start_x = last_location['x'] + last_size['width'] - 10
                        start_y = last_location['y'] + last_size['height'] // 2

                        # 计算滑动终点（第一个用户的左侧中心）
                        end_x = first_location['x'] + 10
                        end_y = first_location['y'] + first_size['height'] // 2

                        # 执行滑动操作
                        self.handler.driver.swipe(start_x, start_y, end_x, end_y, 1000)
                        self.handler.logger.info("Swipe operation completed")

                    except Exception as e:
                        self.handler.log_error(f"Error during swipe operation: {str(e)}")

                    # 重新获取在线用户列表
                    self.handler.logger.info("Refreshing online users list...")
                    refreshed_users = self.handler.find_elements_plus('online_user')

                    n = 5
                    if refreshed_users:
                        for i, user in enumerate(refreshed_users):
                            user_text = user.text
                            all_online_user_names.add(user_text)
                            if user_text not in first_five_names:
                                n += 1
                                self.handler.logger.info(f"New user {n}: {user_text}")
                    else:
                        self.handler.logger.warning("Failed to refresh online users list")
                else:
                    # 如果用户数量不超过5个，正常输出所有用户
                    for i, user in enumerate(online_users):
                        user_text = user.text
                        all_online_user_names.add(user_text)
                        # self.handler.logger.info(f"Online user {i + 1}: {user_text}")
                
                # 更新在线用户列表到 InfoManager
                from ..managers.info_manager import InfoManager
                info_manager = InfoManager.instance()
                info_manager.update_online_users(list(all_online_user_names))
            else:
                self.handler.logger.error("No online user found")

            bottom_drawer = self.handler.wait_for_element_plus('bottom_drawer')
            if bottom_drawer:
                self.handler.logger.info(f'Hide online users dialog')
                self.handler.click_element_at(bottom_drawer, 0.5, -0.1)

        except Exception as e:
            self.handler.log_error(f"Error checking user count: {traceback.format_exc()}")
