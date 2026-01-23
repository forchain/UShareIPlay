from appium.webdriver.common.appiumby import AppiumBy

from ..core.base_command import BaseCommand


def create_command(controller):
    fav_command = FavCommand(controller)
    controller.fav_command = fav_command
    return fav_command


command = None


class FavCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = controller.music_handler

    async def process(self, message_info, parameters):
        """处理 fav 命令
        参数:
            无参数: 直接播放所有收藏
            两个参数及以上(第一个为 0 或 lang, 其余为语言名): 筛选语言后播放
            两个参数及以上(第一个为 1 或 genre, 其余为流派名): 筛选流派后播放
            两个参数及以上(第一个为 2 或 search, 其余为关键字): 收藏内搜索并播放搜索结果列表
        """
        self.soul_handler.ensure_mic_active()

        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()

        if len(parameters) == 0:
            # 无参数，直接播放所有收藏
            playing_info = self.play_favorites_all()
            if 'error' not in playing_info:
                info_manager.player_name = message_info.nickname
                info_manager.current_playlist_name = "O Station"
            return playing_info

        # 有参数：第一个参数为子命令，其余为参数内容（允许带空格）
        subcmd = str(parameters[0]).lower()
        arg = ' '.join(parameters[1:]).strip()
        if not arg:
            return {'error': '参数错误，使用方式: :fav 或 :fav 0 语言名 或 :fav 1 流派名 或 :fav 2 关键字'}

        if subcmd in ['0', 'lang']:
            language = arg
            playing_info = self.play_favorites_by_language(language)
            if 'error' not in playing_info:
                info_manager.player_name = message_info.nickname
                # 与 play_favorites_by_language 内的 title 规则保持一致
                playlist_name = language
                if language == '粤语':
                    playlist_name = '粤音'
                elif language == '英语':
                    playlist_name = '英乐'
                info_manager.current_playlist_name = playlist_name
            return playing_info

        if subcmd in ['1', 'genre']:
            genre = arg
            playing_info = self.play_favorites_by_genre(genre)
            if 'error' not in playing_info:
                info_manager.player_name = message_info.nickname
                info_manager.current_playlist_name = genre
            return playing_info

        if subcmd in ['2', 'search']:
            keyword = arg
            playing_info = self.play_favorites_by_search(keyword)
            if 'error' not in playing_info:
                info_manager.player_name = message_info.nickname
                info_manager.current_playlist_name = keyword
            return playing_info

        return {'error': f'第一个参数必须是 0/lang 或 1/genre 或 2/search，当前为: {parameters[0]}'}

    def play_favorites_all(self):
        """导航到收藏并播放所有"""
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")

        my_nav = self.handler.wait_for_element_clickable_plus('my_nav')
        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        # Click on favorites button
        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

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

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title_manager.set_next_title("O Station")
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': ''}

    def play_favorites_by_language(self, language):
        """导航到收藏，筛选指定语言，然后播放所有
        
        参数:
            language: 要筛选的语言名称，如"粤语"
        """
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")

        my_nav = self.handler.wait_for_element_clickable_plus('my_nav')
        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        # Click on favorites button
        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

        # Click on filter button
        filter_favourite = self.handler.wait_for_element_clickable_plus('filter_favourite')
        if not filter_favourite:
            return {'error': 'Cannot find filter button'}
        filter_favourite.click()
        self.handler.logger.info("Clicked filter button")

        # Scroll container to find the language button
        key, element, found_languages = self.handler.scroll_container_until_element(
            'favourite_option',  # element_key
            'favourite_languages',  # container_key
            'left',  # direction: 向左滑动
            'text',  # attribute_name
            language,  # attribute_value: 用户指定的语言，如"粤语"
            max_swipes=10
        )

        if not element:
            # 返回找到的所有语言供用户参考
            languages_str = ', '.join(found_languages) if found_languages else '无'
            return {'error': f'找不到语言: {language}。可用语言: {languages_str}'}

        # Click the language button
        element.click()
        self.handler.logger.info(f"Clicked language button: {language}")

        # Wait a moment for the filter to take effect
        import time
        time.sleep(0.5)

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

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title = language if language else 'O Station'
        if language == '粤语':
            title = '粤音'
        elif language == '英语':
            title = '英乐'

        title_manager.set_next_title(title)
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': '', 'language': language}

    def play_favorites_by_genre(self, genre):
        """导航到收藏，筛选指定流派，然后播放所有
        
        参数:
            genre: 要筛选的流派名称，如"流行"
        """
        if not self.handler.switch_to_app():
            return {'error': 'Cannot switch to qq music'}
        self.handler.logger.info(f"Switched to QQ Music app")

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")

        my_nav = self.handler.wait_for_element_clickable_plus('my_nav')
        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        # Click on favorites button
        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

        # Click on filter button
        filter_favourite = self.handler.wait_for_element_clickable_plus('filter_favourite')
        if not filter_favourite:
            return {'error': 'Cannot find filter button'}
        filter_favourite.click()
        self.handler.logger.info("Clicked filter button")

        # Scroll container to find the genre button
        key, element, found_genres = self.handler.scroll_container_until_element(
            'favourite_option',  # element_key
            'favourite_genres',  # container_key
            'left',  # direction: 向左滑动
            'text',  # attribute_name
            genre,  # attribute_value: 用户指定的流派，如"流行"
            max_swipes=10
        )

        if not element:
            # 返回找到的所有流派供用户参考
            genres_str = ', '.join(found_genres) if found_genres else '无'
            return {'error': f'找不到流派: {genre}。可用流派: {genres_str}'}

        # Click the genre button
        element.click()
        self.handler.logger.info(f"Clicked genre button: {genre}")

        # Wait a moment for the filter to take effect
        import time
        time.sleep(0.5)

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

        self.handler.list_mode = 'favorites'
        # 使用 title_manager 和 topic_manager 管理标题和话题
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        title_manager = TitleManager.instance()
        topic_manager = TopicManager.instance()
        title = genre if genre else 'O Station'
        title_manager.set_next_title(title)
        topic_manager.change_topic(song_text)

        return {'song': song_text, 'singer': singer_text, 'album': '', 'genre': genre}

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

        self.handler.navigate_to_home()
        self.handler.logger.info("Navigated to home page")

        my_nav = self.handler.wait_for_element_clickable_plus('my_nav')
        my_nav.click()
        self.handler.logger.info("Clicked personal info navigation button")

        fav_entry = self.handler.wait_for_element_clickable_plus('fav_entry')
        fav_entry.click()
        self.handler.logger.info("Clicked favorites button")

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

        # 播放后，像 playlist/singer 命令那样，从“正在播放”列表中获取完整歌单，并取第一项作为话题
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

        self.handler.list_mode = 'favorites'

        # 5) 标题设置为关键字；话题设置为搜索到的第一首歌
        from ..managers.title_manager import TitleManager
        from ..managers.topic_manager import TopicManager
        from ..managers.info_manager import InfoManager
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
            'playlist': playlist_text,
            'first_song': first_song,
            'keyword': keyword,
            'song': first_song,
            'singer': '',
            'album': '',
        }
