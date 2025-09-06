import re
import traceback
from ..core.singleton import Singleton


class MusicManager(Singleton):
    """
    音乐管理器 - 管理音乐播放相关功能
    单例模式，提供统一的音乐管理服务
    专注于系统级音乐控制，与具体播放器无关
    """
    
    def __init__(self):
        # 获取 QQMusicHandler 单例实例
        from ..handlers.qq_music_handler import QQMusicHandler
        self.music_handler = QQMusicHandler.instance()
        self.logger = self.music_handler.logger
        self.driver = self.music_handler.driver
    
    def play_song(self, song_query: str) -> dict:
        """
        播放指定歌曲
        Args:
            song_query: 歌曲查询字符串
        Returns:
            dict: 播放结果
        """
        try:
            self.logger.info(f"Attempting to play song: {song_query}")
            
            if not self.music_handler.switch_to_app():
                return {'error': 'Failed to switch to music app'}
            
            # 搜索歌曲
            search_result = self.music_handler.search_song(song_query)
            if 'error' in search_result:
                return search_result
            
            # 播放找到的歌曲
            play_result = self.music_handler.play_first_result()
            if 'error' in play_result:
                return play_result
            
            return {
                'song': search_result.get('song', song_query),
                'singer': search_result.get('singer', 'Unknown'),
                'album': search_result.get('album', 'Unknown')
            }
            
        except Exception as e:
            self.logger.error(f"Error playing song: {traceback.format_exc()}")
            return {'error': str(e)}
    
    def pause_resume(self, should_pause: bool) -> dict:
        """
        暂停或恢复播放 - 系统级控制
        Args:
            should_pause: True为暂停，False为恢复
        Returns:
            dict: 操作结果
        """
        try:
            action = "暂停" if should_pause else "恢复"
            self.logger.info(f"Attempting to {action} playback")
            
            # 发送系统级媒体控制键
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_PLAY_PAUSE'
                }
            )
            self.logger.info("Sent media play/pause key event")
            
            return {'action': action}
            
        except Exception as e:
            error_msg = str(e)
            if "InvalidSessionIdException" in error_msg or "session is either terminated" in error_msg:
                self.logger.warning("Appium session terminated, cannot control playback")
                return {'error': 'Appium session terminated', 'session_lost': True}
            else:
                self.logger.error(f"Error controlling playback: {traceback.format_exc()}")
                return {'error': error_msg}
    
    def skip_song(self) -> dict:
        """
        跳过当前歌曲 - 系统级控制
        Returns:
            dict: 操作结果
        """
        try:
            self.logger.info("Attempting to skip current song")
            
            # 获取当前歌曲信息
            current_info = self.get_current_song_info()
            
            # 发送系统级媒体控制键
            self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'input keyevent KEYCODE_MEDIA_NEXT'
                }
            )
            self.logger.info(f"Skipped {current_info.get('song', 'Unknown')} by {current_info.get('singer', 'Unknown')}")
            
            return {
                'song': current_info.get('song', 'Unknown'),
                'singer': current_info.get('singer', 'Unknown')
            }
            
        except Exception as e:
            error_msg = str(e)
            if "InvalidSessionIdException" in error_msg or "session is either terminated" in error_msg:
                self.logger.warning("Appium session terminated, cannot skip song")
                return {'error': 'Appium session terminated', 'session_lost': True}
            else:
                self.logger.error(f"Error skipping song: {traceback.format_exc()}")
                return {'error': error_msg}
    
    def get_current_song_info(self) -> dict:
        """
        获取当前播放歌曲信息 - 系统级获取
        Returns:
            dict: 歌曲信息
        """
        try:
            # 通过系统级媒体会话获取播放信息
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys media_session'
                }
            )

            # 解析元数据
            metadata = {}
            state = "Unknown"

            if not result:
                self.logger.error("Failed to get playback information")
                return {'error': 'Failed to get playback information'}

            # 获取元数据
            meta_match = re.search(r'metadata: size=\d+, description=(.*?)(?=\n)', result)
            if meta_match:
                meta_parts = meta_match.group(1).split(', ')
                if len(meta_parts) >= 3:
                    metadata = {
                        'song': meta_parts[0],
                        'singer': meta_parts[1],
                        'album': meta_parts[2]
                    }

            # 获取播放状态
            state_match = re.search(r'state=PlaybackState {state=(\d+)', result)
            if state_match:
                state_code = int(state_match.group(1))
                state = {
                    0: "None",
                    1: "Stopped",
                    2: "Paused",
                    3: "Playing",
                    4: "Fast Forwarding",
                    5: "Rewinding",
                    6: "Buffering",
                    7: "Error",
                    8: "Connecting",
                    9: "Skipping to Next",
                    10: "Skipping to Previous",
                    11: "Skipping to Queue Item"
                }.get(state_code, "Unknown")

            return {
                'song': metadata.get('song', 'Unknown'),
                'singer': metadata.get('singer', 'Unknown'),
                'album': metadata.get('album', 'Unknown'),
                'state': state
            }
            
        except Exception as e:
            error_msg = str(e)
            if "InvalidSessionIdException" in error_msg or "session is either terminated" in error_msg:
                self.logger.warning("Appium session terminated, cannot get song info")
                return {'error': 'Appium session terminated', 'session_lost': True}
            else:
                self.logger.error(f"Error getting song info: {traceback.format_exc()}")
                return {'error': error_msg}
    
    def get_volume_level(self) -> int:
        """
        获取当前音量级别 - 系统级获取
        Returns:
            int: 音量级别 (0-15)
        """
        try:
            # 通过系统服务获取音量
            result = self.driver.execute_script(
                'mobile: shell',
                {
                    'command': 'dumpsys audio'
                }
            )

            # 解析音量级别
            if result:
                # 按 "- STREAM_MUSIC:" 分割
                parts = result.split('- STREAM_MUSIC:')
                if len(parts) > 1:
                    # 在第二部分中找到第一个 streamVolume
                    match = re.search(r'streamVolume:(\d+)', parts[1])
                    if match:
                        volume = int(match.group(1))
                        self.logger.info(f"Current volume: {volume}")
                        return volume
            return 0
        except Exception as e:
            error_msg = str(e)
            if "InvalidSessionIdException" in error_msg or "session is either terminated" in error_msg:
                self.logger.warning("Appium session terminated, cannot get volume level")
                return 0
            else:
                self.logger.error(f"Error getting volume level: {traceback.format_exc()}")
                return 0
    
    def adjust_volume(self, target_volume: int) -> dict:
        """
        调整音量到指定级别 - 系统级控制
        Args:
            target_volume: 目标音量级别 (0-15)
        Returns:
            dict: 操作结果
        """
        try:
            current_volume = self.get_volume_level()
            delta = target_volume - current_volume
            
            if delta == 0:
                return {'volume': current_volume}
            
            # 调整音量
            if delta < 0:
                # 降低音量
                times = abs(delta)
                for i in range(times):
                    self.music_handler.press_volume_down()
                    self.logger.info(f"Decreased volume ({i + 1}/{times})")
            else:
                # 提高音量
                times = delta
                for i in range(times):
                    self.music_handler.press_volume_up()
                    self.logger.info(f"Increased volume ({i + 1}/{times})")

            # 获取最终音量级别
            final_volume = self.get_volume_level()
            self.logger.info(f"Adjusted volume to {final_volume}")
            return {'volume': final_volume}
            
        except Exception as e:
            error_msg = str(e)
            if "InvalidSessionIdException" in error_msg or "session is either terminated" in error_msg:
                self.logger.warning("Appium session terminated, cannot adjust volume")
                return {'error': 'Appium session terminated', 'session_lost': True}
            else:
                self.logger.error(f"Error adjusting volume: {traceback.format_exc()}")
                return {'error': error_msg}
