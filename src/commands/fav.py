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
            两个参数(第一个为 0 或 lang, 第二个为语言名): 筛选语言后播放
        """
        self.soul_handler.ensure_mic_active()

        from ..managers.info_manager import InfoManager
        info_manager = InfoManager.instance()

        if len(parameters) == 0:
            # 无参数，直接播放所有收藏
            playing_info = self.play_favorites_all()
            info_manager.player_name = message_info.nickname
            return playing_info
        elif len(parameters) == 2:
            # 两个参数，检查第一个参数是否为 0 或 lang
            if parameters[0] in ['0', 'lang']:
                language = parameters[1]
                playing_info = self.play_favorites_by_language(language)
                info_manager.player_name = message_info.nickname
                return playing_info
            else:
                return {'error': f'第一个参数必须是 0 或 lang，当前为: {parameters[0]}'}
        else:
            return {'error': '参数错误，使用方式: :fav 或 :fav 0 语言名'}

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
            'favourite_language',  # element_key
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
