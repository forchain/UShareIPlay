from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.common import AppiumOptions
from ..soul.soul_handler import SoulHandler
from ..music.qq_music_handler import QQMusicHandler
from ..utils.command_parser import CommandParser

class AppController:
    def __init__(self, config):
        self.config = config
        self.driver = self._init_driver()
        self.soul_handler = SoulHandler(self.driver, config['soul'])
        self.music_handler = QQMusicHandler(self.driver, config['qq_music'])
        self.command_parser = CommandParser(config['command'])

    def _init_driver(self):
        options = AppiumOptions()
        
        # 设置基本能力
        options.set_capability('platformName', self.config['device']['platform_name'])
        options.set_capability('platformVersion', self.config['device']['platform_version'])
        options.set_capability('deviceName', self.config['device']['name'])
        options.set_capability('automationName', self.config['device']['automation_name'])
        options.set_capability('noReset', self.config['device']['no_reset'])
        
        # 设置应用信息
        options.set_capability('appPackage', self.config['soul']['package_name'])
        options.set_capability('appActivity', self.config['soul']['chat_activity'])
        
        # 修改这里的 URL 构建
        server_url = f"http://{self.config['appium']['host']}:{self.config['appium']['port']}"
        return webdriver.Remote(command_executor=server_url, options=options)

    def start_monitoring(self):
        while True:
            try:
                # 监控 Soul 消息
                message = self.soul_handler.get_latest_message()
                if message and self.command_parser.is_valid_command(message):
                    song, singer = self.command_parser.parse_command(message)
                    
                    # 切换到QQ音乐播放
                    self.music_handler.play_music(song, singer)
                    
                    # 返回 Soul 发送状态
                    response = self.config['command']['response_template'].format(
                        song=song,
                        singer=singer
                    )
                    self.soul_handler.send_message(response)
                    
            except KeyboardInterrupt:
                print("\nStopping the monitoring...")
                break
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                import time
                time.sleep(1)  # 添加延迟避免过快循环