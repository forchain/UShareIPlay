import re

class LyricsFormatter:
    def __init__(self, tags):
        self.tags = tags
        self.chinese_languages = ['国语', '粤语', '闽南语', '日语', '韩语']

    def format_lyrics(self, text, language=None):
        """Format lyrics text with tags and language-specific formatting"""
        # Format tags
        formatted_text = self._format_tags(text)
        
        # Split text into metadata and lyrics using "歌词" tag
        parts = formatted_text.split("歌词")
        if len(parts) != 2:
            parts = formatted_text.split("歌曲简介")
            if len(parts) == 2:
                return parts[0] + "\n No lyrics available"
            parts = formatted_text.split("相关曲谱")
            if len(parts) == 2:
                return parts[0] + "\n No lyrics available"
            return formatted_text  # Return original if no "歌词" tag found
            
        metadata, lyrics = parts[0], parts[1]
        
        # Format lyrics based on language
        if language:
            if language in self.chinese_languages:
                formatted_lyrics = self._format_chinese_lyrics(lyrics)
            elif language == '英语':
                formatted_lyrics = self._format_english_lyrics(lyrics)
            else:
                formatted_lyrics = lyrics
        else:
            formatted_lyrics = lyrics
            
        # Combine metadata and formatted lyrics
        return f"{metadata}歌词{formatted_lyrics}"

    def _format_tags(self, text):
        """Replace space after tags with line breaks"""
        formatted_text = text
        for tag in self.tags:
            # Match tag followed by space
            formatted_text = formatted_text.replace(f' {tag}', f'\n{tag}')
        return formatted_text

    def _format_chinese_lyrics(self, text):
        """Format Chinese lyrics by replacing spaces with line breaks"""
        return text.replace(' ', '\n')

    def _format_english_lyrics(self, text):
        """Format English lyrics by adding line breaks before capital letters followed by lowercase words"""
        # Add line break before capital letter that is followed by lowercase word
        return re.sub(r'([A-Z][a-z]+)\s+([a-z]+)', r'\n\1 \2', text)