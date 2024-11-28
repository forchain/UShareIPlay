import unittest
import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.lyrics_formatter import LyricsFormatter

class TestLyricsFormatter(unittest.TestCase):
    def setUp(self):
        # Get tags from config
        config_file = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        with open(config_file, 'r', encoding='utf-8') as f:
            import yaml
            config = yaml.safe_load(f)
        
        # Get lyrics tags from lyrics command config
        lyrics_tags = next(
            (cmd.get('tags', []) for cmd in config['commands'] if cmd['prefix'] == 'lyrics'),
            []
        )
        self.formatter = LyricsFormatter(lyrics_tags)

    def test_full_chinese_lyrics(self):
        """Test complete Chinese lyrics formatting"""
        input_text = """基础信息 歌曲名 一往情深 歌手 游鸿明 语种 国语 专辑 33多料金选 专辑发行时间 2002-01-01 幕后团队 作词 李姚 作曲 殷文 歌词 明知不该为情感伤 一切已成过往 你已不在我的心上 但却又忍不住想 想你是否记得我的肩膀 想你现在依偎在谁的身旁 如果能够倒转时光 重新再来一场 是不是结局还是会一样 我知道试着遗忘 可以让人变的比较坚强 但是爱过的人不是你能说忘就忘 一往情深可惜有缘无份 爱一个人注定要为情所困 今世今生你是我最爱的人 又何必问自己的心还疼不疼 明知不该为情感伤"""
        result = self.formatter.format_lyrics(input_text, "国语")
        print(result)

    def test_full_english_lyrics(self):
        """Test complete Chinese lyrics formatting"""
        input_text = """基础信息 歌曲名 Ambien Slide 歌手 Cigarettes After Sex 语种 英语 流派 另类音乐 专辑 X's (Explicit) 专辑发行时间 2024-07-12 幕后团队 作词 Greg Gonzalez 作曲 Greg Gonzalez 制作人 Greg Gonzalez 歌词 Ambien Slide - Cigarettes After Sex Lyrics by：Greg Gonzalez Composed by：Greg Gonzalez Produced by：Greg Gonzalez Said you couldn't sleep To know I'd been with someone else Takes d**gs to shut it out And that's how you'll get over it Take my love with zolpidem You said you couldn't help it"""
        result = self.formatter.format_lyrics(input_text, "英语")
        print(result)

if __name__ == '__main__':
    unittest.main()