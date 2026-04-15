from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.base_command import BaseCommand

import re
import time


def create_command(controller):
    fav_command = FavCommand(controller)
    controller.fav_command = fav_command
    return fav_command


command = None


class FavCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = controller.music_handler

    def _xpath_textview_text_equals(self, text_value: str) -> str:
        """
        Build an XPath for android.widget.TextView[@text=...], safe for quotes.
        """
        if '"' not in text_value:
            return f'//android.widget.TextView[@text="{text_value}"]'
        if "'" not in text_value:
            return f"//android.widget.TextView[@text='{text_value}']"
        # Fallback: concat with double quotes split (rare in our use)
        parts = text_value.split('"')
        concat_parts = []
        for idx, part in enumerate(parts):
            if part:
                concat_parts.append(f'"{part}"')
            if idx != len(parts) - 1:
                concat_parts.append("'\"'")
        return f"//android.widget.TextView[@text=concat({', '.join(concat_parts)})]"

    def _apply_favourite_filter_keyword(self, keyword: str):
        """
        新版“筛选歌曲”页：同页展示歌手/语种/流派。
        流程：点筛选 -> 点选关键字(TextView[@text]) -> 点“确定（xxx首）”
        """
        filter_favourite = self.handler.wait_for_element_clickable_plus('filter_favourite')
        if not filter_favourite:
            return {'error': 'Cannot find filter button'}
        filter_favourite.click()
        self.handler.logger.info("Clicked filter button")

        option_xpath = self._xpath_textview_text_equals(keyword)
        option = self.handler.wait_for_element_clickable(AppiumBy.XPATH, option_xpath, timeout=8)
        if not option:
            return {'error': f'找不到筛选项: {keyword}'}
        option.click()
        self.handler.logger.info(f"Clicked filter option: {keyword}")

        # 等待“确定（xxx首）”按钮出现/更新
        time.sleep(0.25)
        confirm_xpath = '//android.widget.TextView[starts-with(@text,"确定（") and contains(@text,"首）")]'
        confirm = self.handler.wait_for_element_clickable(AppiumBy.XPATH, confirm_xpath, timeout=8)
        if not confirm:
            return {'error': 'Cannot find confirm button: 确定（xxx首）'}
        confirm_text = (confirm.text or "").strip()
        confirm.click()
        self.handler.logger.info("Clicked confirm button")

        # 等待回到收藏列表（UI 动画/数据刷新）
        time.sleep(0.35)
        count = None
        if confirm_text:
            m = re.search(r"确定（(\d+)首）", confirm_text)
            if m:
                try:
                    count = int(m.group(1))
                except Exception:
                    count = None
        return {'count': count}

    async def process(self, message_info, parameters):
        """处理 fav 命令
        参数:
            无参数: 直接播放所有收藏
            两个参数及以上(第一个为 0 或 type, 其余为分类关键字): 筛选后播放
            两个参数及以上(第一个为 2 或 search, 其余为关键字): 收藏内搜索并播放搜索结果列表
        """
        self.soul_handler.ensure_mic_active()

        from ushareiplay.managers.info_manager import InfoManager
        info_manager = InfoManager.instance()

        if len(parameters) == 0:
            # 无参数，直接播放所有收藏
            playing_info = self.play_favorites_all()
            if 'error' in playing_info:
                return playing_info

            info_manager.player_name = message_info.nickname
            info_manager.current_playlist_name = "O Station"
            return playing_info

        # 有参数：第一个参数为子命令，其余为参数内容（允许带空格）
        subcmd = str(parameters[0]).lower()
        arg = ' '.join(parameters[1:]).strip()
        if not arg:
            return {'error': '参数错误，使用方式: :fav 或 :fav type 关键字 或 :fav 2 关键字'}

        if subcmd in ['0', 'type']:
            keyword = arg
            playing_info = self.play_favorites_by_type(keyword)
            if 'error' in playing_info:
                return playing_info

            info_manager.player_name = message_info.nickname
            # 与 play_favorites_by_type 内的 title 规则保持一致
            playlist_name = keyword
            if keyword == '粤语':
                playlist_name = '粤音'
            elif keyword == '英语':
                playlist_name = '英乐'
            info_manager.current_playlist_name = playlist_name
            return playing_info

        if subcmd in ['2', 'search']:
            keyword = arg
            playing_info = self.play_favorites_by_search(keyword)
            if 'error' in playing_info:
                return playing_info

            info_manager.player_name = message_info.nickname
            info_manager.current_playlist_name = keyword
            return playing_info

        return {'error': f'第一个参数必须是 0/type 或 2/search，当前为: {parameters[0]}'}

    def play_favorites_all(self):
        """导航到收藏并播放所有"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info("Switched to QQ Music app")

        err = self.handler.open_favorites_entry()
        if err:
            return err

        result_item = self.handler.try_find_element_plus('result_item')
        song_text = None
        singer_text = None
        if result_item:
            elements = self.handler.find_child_elements(result_item, AppiumBy.CLASS_NAME, 'android.widget.TextView')
            if len(elements) >= 3:
                song_text = elements[1].text
                singer_text = elements[2].text

        play_fav = self.handler.wait_for_element_clickable_plus('play_all')
        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        # 播放后先回到 QQ 音乐首页，再去 Soul 设置标题/话题
        self.handler.navigate_to_home()
        self.handler.logger.info("fav 播放全部收藏后已回到 QQ 音乐首页，准备设置标题和话题")

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ushareiplay.managers.title_manager import TitleManager
        from ushareiplay.managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title("O Station")
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}

    def play_favorites_by_type(self, keyword: str):
        """导航到收藏，按关键字筛选，然后播放所有

        参数:
            keyword: 筛选关键字，如“国语”“流行”“张国荣”
        """
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info("Switched to QQ Music app")

        err = self.handler.open_favorites_entry()
        if err:
            return err

        filter_result = self._apply_favourite_filter_keyword(keyword)
        if isinstance(filter_result, dict) and 'error' in filter_result:
            return filter_result
        count = filter_result.get('count') if isinstance(filter_result, dict) else None

        # Get song info from the first result
        result_item = self.handler.try_find_element_plus('result_item')
        song_text = None
        singer_text = None
        if result_item:
            elements = self.handler.find_child_elements(result_item, AppiumBy.CLASS_NAME, 'android.widget.TextView')
            if len(elements) >= 3:
                song_text = elements[1].text
                singer_text = elements[2].text

        # Click play all button
        play_fav = self.handler.wait_for_element_clickable_plus('play_all')
        if not play_fav:
            return {'error': 'Cannot find play all button'}
        play_fav.click()
        self.handler.logger.info("Clicked play all button")

        # 播放后先回到 QQ 音乐首页，再去 Soul 设置标题/话题
        self.handler.navigate_to_home()
        self.handler.logger.info("fav 按语言筛选播放后已回到 QQ 音乐首页，准备设置标题和话题")

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ushareiplay.managers.title_manager import TitleManager
        from ushareiplay.managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title = keyword if keyword else 'O Station'
        if keyword == '粤语':
            title = '粤音'
        elif keyword == '英语':
            title = '英乐'

        title_manager.set_next_title(title)
        topic_manager.change_topic(song_text)

        result = {'song': song_text, 'singer': singer_text, 'album': '', 'type': keyword}
        if count is not None:
            result['count'] = count
        return result

    def play_favorites_by_search(self, keyword: str):
        """导航到收藏，显示收藏内搜索框，搜索关键字后播放搜索结果列表

        流程（与需求一致）：
        1) 在“全部播放”按钮上下滑动其高度单位，以触发显示搜索框
        2) 找到 search_box 并点击激活
        3) 粘贴关键字
        4) 点击 play_favourite_search 播放搜索的歌曲列表
        5) 标题=关键字；话题=搜索到的第一首歌
        6) 通过 InfoManager.current_playlist_name 广播歌单（在 process 内设置）
        """
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info("Switched to QQ Music app")

        err = self.handler.open_favorites_entry()
        if err:
            return err

        # 1) 在“全部播放”按钮上下滑动其高度，目的是显示搜索框
        play_all_btn = self.handler.wait_for_element_clickable_plus('play_all')
        if not play_all_btn:
            return {'error': 'Cannot find play all button'}

        loc = play_all_btn.location
        size = play_all_btn.size
        cx = int(loc["x"] + size["width"] * 0.5)
        cy = int(loc["y"] + size["height"] * 0.5)
        dy = max(60, int(size["height"]))

        self.handler._perform_swipe(cx, cy, cx, cy + dy, duration_ms=260)

        # 2) 找到 search_box 并点击激活搜索框
        search_box = self.handler.wait_for_element_clickable_plus('search_box')
        if not search_box:
            return {'error': 'Cannot find search box in favourites'}
        search_box.click()
        self.handler.logger.info("Clicked favourite search box")

        favourite_search = self.handler.wait_for_element_plus('favourite_search')
        if not favourite_search:
            return {'error': 'Cannot find favourite search'}

        # 3) 粘贴关键字
        self.handler.set_clipboard_text(keyword)
        self.handler.paste_text()
        self.handler.logger.info(f"Pasted keyword: {keyword}")

        # 4) 点击 play_favourite_search 播放搜索的歌曲列表
        play_search = self.handler.wait_for_element_clickable_plus('play_favourite_search')
        if not play_search:
            return {'error': 'Cannot find play_favourite_search button'}
        play_search.click()
        self.handler.logger.info("Clicked play_favourite_search button")

        # 播放后，从“正在播放”列表中获取完整歌单
        playlist_info = self.handler.get_playlist_info()
        if 'error' in playlist_info:
            return playlist_info

        playlist_text = playlist_info.get('playlist', '').strip()
        if not playlist_text:
            return {'error': 'Playlist content is empty'}

        # 第一行作为“第一首歌”的描述（形如 歌曲名+歌手）
        first_line = playlist_text.splitlines()[0].strip()
        parts = first_line.split('-')
        first_song = parts[0].strip() if len(parts) > 1 else first_line

        # 播放后先回到 QQ 音乐首页，再去 Soul 设置标题/话题
        self.handler.navigate_to_home()
        self.handler.logger.info("fav 收藏内搜索播放后已回到 QQ 音乐首页，准备设置标题和话题")

        self.handler.list_mode = 'favorites'

        # 5) 标题设置为关键字；话题设置为搜索到的第一首歌
        from ushareiplay.managers.title_manager import TitleManager
        from ushareiplay.managers.topic_manager import TopicManager
        from ushareiplay.managers.info_manager import InfoManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        info_manager = InfoManager.instance()

        title_manager.set_next_title(keyword if keyword else "O Station")
        topic_manager.change_topic(first_song or keyword)
        # 由 InfoManager.current_playlist_name + InfoCommand 实现“回到 Soul 后广播这个列表”
        info_manager.current_playlist_name = keyword

        # 返回整个歌单文本，供上层在 Soul 中广播
        # 同时补充 song/singer 字段，以兼容默认的 response_template
        return {
            'playlist': keyword,
            'first_song': first_song,
            'keyword': keyword,
            'song': first_song,
            'singer': '',
            'album': '',
        }
