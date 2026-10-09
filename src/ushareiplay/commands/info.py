from ushareiplay.core.base_command import BaseCommand


class InfoCommand(BaseCommand):
    handler_attr = 'soul_handler'

    async def do_process(self, message_info, parameters):
        # 从缓存获取播放信息
        info_manager = self.info_manager
        result = info_manager.ensure_cached_release_date()

        # 如果缓存未初始化，使用默认值
        if result is None:
            result = {
                "song": "Unknown",
                "singer": "Unknown",
                "album": "Unknown",
                "release_date": "",
                "state": None,
            }
        else:
            result["release_date"] = result.get("release_date") or ""

        # 追加播放器信息和在线用户列表
        result["player"] = info_manager.player_name

        online_users = info_manager.get_online_users()
        if online_users:
            formatted_users = self._format_online_users(online_users)
            result["online_users"] = (
                f"{len(online_users)}人: {', '.join(formatted_users)}"
            )
        else:
            result["online_users"] = "列表暂未更新"

        # 追加派对时长信息
        party_duration = info_manager.get_party_duration_info()
        result["party_duration"] = party_duration if party_duration else ""

        # 追加当前歌单信息
        playlist_info = info_manager.get_playlist_info()
        if playlist_info and playlist_info.get("name"):
            playlist_type_map = {
                "singer": "歌手",
                "playlist": "歌单",
                "album": "专辑",
                "radio": "电台",
                "favorites": "收藏",
                "radar": "雷达",
                "unknown": "未知",
            }
            ptype = playlist_type_map.get(playlist_info["type"], playlist_info["type"])
            result["current_playlist"] = (
                f"[{ptype}] {playlist_info['name']} (by {result['player']})"
            )
        else:
            result["current_playlist"] = "暂无活跃歌单"

        from ushareiplay.handlers.qq_music_handler import QQMusicHandler
        music_handler = QQMusicHandler.instance()
        play_mode_key = getattr(music_handler, 'play_mode_key', 'unknown') if music_handler else 'unknown'
        result["play_mode_key"] = play_mode_key
        result["play_mode"] = music_handler.play_mode_key_to_name(play_mode_key) if music_handler else "未知"

        rec_status = info_manager.recommendation_enabled
        if rec_status is True:
            result["party_recommendation"] = "开放"
        elif rec_status is False:
            result["party_recommendation"] = "关闭"
        else:
            result["party_recommendation"] = "未知"

        return result

    def _format_online_users(self, online_users):
        """
        格式化在线用户列表，标注管理员身份与麦位编号。
        格式规范：
          - 仅为管理且不在麦：昵称(管理)
          - 仅在麦非管理：昵称(N号)
          - 既是管理又在麦：昵称(管理, N号)
          - 既非管理又不在麦：昵称
        """
        room_admins = set()
        try:
            from ushareiplay.managers.admin_manager import AdminManager
            if AdminManager.is_initialized():
                room_admins = AdminManager.instance().get_room_admins()
        except Exception:
            pass

        seated_users = {}
        try:
            from ushareiplay.managers.seat_manager.seat_observation import SeatObservationManager
            if SeatObservationManager.is_initialized():
                seated_users = SeatObservationManager.instance().get_all_seated_users()
        except Exception:
            pass

        formatted = []
        for user in sorted(online_users):
            is_admin = user in room_admins
            seat_num = seated_users.get(user)
            tags = []
            if is_admin:
                tags.append("管理")
            if seat_num is not None:
                tags.append(f"{seat_num}号")
            if tags:
                formatted.append(f"{user}({', '.join(tags)})")
            else:
                formatted.append(user)
        return formatted

    def update(self):
        """Update playback info and user count - delegates to InfoManager"""
        # Update playback info (handles playback info changes, quality check, etc.)
        self.info_manager.update()
