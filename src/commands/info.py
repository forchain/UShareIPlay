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

        # 追加定时器状态
        try:
            from ..managers.timer_manager import TimerManager
            timer_manager = TimerManager.instance()
            timers = timer_manager.get_timers()
            total = len(timers)
            enabled = sum(1 for t in timers.values() if t.get('enabled', False))
            if timer_manager.is_running():
                result['timer_status'] = f"定时器: 运行中，共 {total} 个 ({enabled} 个已启用)"
            else:
                result['timer_status'] = f"定时器: 已停止，共 {total} 个"
        except Exception:
            result['timer_status'] = "定时器: 状态未知"
        
        return result

    def update(self):
        """Update playback info and user count - delegates to InfoManager"""
        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()
        
        # Update playback info (handles playback info changes, quality check, etc.)
        info_manager.update()
