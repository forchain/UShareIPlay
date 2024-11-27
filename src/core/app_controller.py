from appium import webdriver
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from appium.options.common import AppiumOptions
from ..soul.soul_handler import SoulHandler
from ..music.qq_music_handler import QQMusicHandler
from ..utils.command_parser import CommandParser
import time

class AppController:
    def __init__(self, config):
        self.config = config
        self.driver = self._init_driver()
        self.soul_handler = SoulHandler(self.driver, config['soul'])
        self.music_handler = QQMusicHandler(self.driver, config['qq_music'])
        self.command_parser = CommandParser(config['commands'])

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
        
        server_url = f"http://{self.config['appium']['host']}:{self.config['appium']['port']}"
        return webdriver.Remote(command_executor=server_url, options=options)

    def start_monitoring(self):
        while True:
            try:
                # Monitor Soul messages
                messages = self.soul_handler.get_latest_message()
                if messages:
                    for message in messages:
                        if self.command_parser.is_valid_command(message):
                            command_info = self.command_parser.parse_command(message)
                            if command_info:
                                # Handle different commands using match-case
                                response = None
                                match command_info['command']:
                                    case 'play':
                                        # Play music and get info
                                        query = ' '.join(command_info['parameters'])
                                        playing_info = self.music_handler.play_music(query)
                                        
                                        # Send status back to Soul using command's template
                                        response = command_info['response_template'].format(
                                            song=playing_info['song'],
                                            singer=playing_info['singer']
                                        )
                                    case 'skip':
                                        # Skip to next song
                                        playing_info = self.music_handler.skip_song()
                                        
                                        # Send status back to Soul using command's template
                                        response = command_info['response_template'].format(
                                            song=playing_info['song'],
                                            singer=playing_info['singer']
                                        )
                                    case 'next':
                                        # Play music and get info
                                        query = ' '.join(command_info['parameters'])
                                        playing_info = self.music_handler.play_next(query)
                                        
                                        # Send status back to Soul using command's template
                                        response = command_info['response_template'].format(
                                            song=playing_info['song'],
                                            singer=playing_info['singer']
                                        )
                                    case 'pause':
                                        # Pause current song
                                        playing_info = self.music_handler.pause_song()
                                        
                                        # Send status back to Soul using command's template
                                        response = command_info['response_template'].format(
                                            song=playing_info['song'],
                                            singer=playing_info['singer']
                                        )
                                    case 'vol+':
                                        # Increase volume
                                        self.music_handler.increase_volume()
                                        response = command_info['response_template']
                                    case 'vol-':
                                        # Decrease volume
                                        self.music_handler.decrease_volume()
                                        response = command_info['response_template']
                                    case _:
                                        print(f"Unknown command: {command_info['command']}")
                                if response:
                                    self.soul_handler.send_message(response)
                time.sleep(9)
            except KeyboardInterrupt:
                print("\nStopping the monitoring...")
                break
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                time.sleep(1)