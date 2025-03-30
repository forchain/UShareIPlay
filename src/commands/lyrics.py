import traceback
from ..core.base_command import BaseCommand
from datetime import datetime, timedelta
import time
import jieba
from langdetect import detect_langs
import langdetect
from html import unescape

# 在导入后设置种子
langdetect.DetectorFactory.seed = 0

def create_command(controller):
    lyrics_command = LyricsCommand(controller)
    controller.lyrics_command = lyrics_command
    return lyrics_command

command = None

class LyricsCommand(BaseCommand):
    def __init__(self, controller):
        super().__init__(controller)
        self.handler = self.soul_handler

    def select_lyrics_tab(self):
        """Select lyrics tab in music player"""
        try:
            # Make sure we're in the music app
            if not self.music_handler.switch_to_app():
                self.handler.logger.error("Failed to switch to music app")
                return False
                
            # Try to find lyrics tab first
            lyrics_tab = self.music_handler.try_find_element_plus('lyrics_tab')
            if not lyrics_tab:
                # If not found, scroll music_tabs to end
                music_tabs = self.music_handler.try_find_element_plus('music_tabs')
                if not music_tabs:
                    return False
                
                # Get size and location for scrolling
                size = music_tabs.size
                location = music_tabs.location
                
                # Scroll to right
                self.music_handler.driver.swipe(
                    location['x'] + size['width'] - 200,  # Start from right
                    location['y'] + size['height'] // 2,
                    location['x'] + 10,  # End at left
                    location['y'] + size['height'] // 2,
                    1000
                )
                
                # Try to find lyrics tab again
                lyrics_tab = self.music_handler.try_find_element_plus('lyrics_tab')
                if not lyrics_tab:
                    return False
                
                lyrics_tab.click()
                
                # Scroll back to left
                self.music_handler.driver.swipe(
                    location['x'] + 200,  # Start from left
                    location['y'] + size['height'] // 2,
                    location['x'] + size['width'] - 10,  # End at right
                    location['y'] + size['height'] // 2,
                    1000
                )
            else:
                lyrics_tab.click()
            
            return True
            
        except Exception as e:
            self.handler.log_error(f"Error selecting lyrics tab: {traceback.format_exc()}")
            return False

    def query_lyrics(self, query, group_num=0):
        """Query lyrics for current song
        Args:
            query: str, lyrics to search for
            group_num: int, number of groups to force
        Returns:
            dict: Result with lyrics groups or error
        """
        # Make sure we're in the music app
        if not self.music_handler.switch_to_app():
            return {'error': 'Failed to switch to music app'}
            
        # If no query provided, construct from current playing info
        if query == "":
            # Get current playing info
            info = self.music_handler.get_playback_info()
            if 'error' in info:
                return {'error': 'Failed to get playback info'}
            
            # Construct search query from current song
            query = f'{info["song"]} {info["singer"]} {info["album"]}'
            self.handler.logger.info(f"Using current song info as query: {query}")
        
        # Search for the song
        if not self.music_handler.query_music(query):
            self.handler.logger.error(f"Failed to query music with query {query}")
            return {'error': f'Failed to find song matching "{query}"'}
        
        # Select lyrics tab after finding the song
        if not self.select_lyrics_tab():
            return {'error': 'Failed to select lyrics tab'}
            
        # Get lyrics text
        lyrics_text = self.music_handler.try_find_element_plus('lyrics_text')
        if not lyrics_text:
            return {'error': f'No lyrics found for "{query}"'}
        lyrics_text.click()

        # Process lyrics - handle HTML entities
        lyrics_content = lyrics_text.text
        lyrics_content = unescape(lyrics_content)  # Unescape HTML entities
        
        # Process lyrics
        lyrics_groups = self.process_lyrics(lyrics_content, force_groups=group_num)
        return {'groups': lyrics_groups}

    def process_lyrics(self, lyrics_text, max_width=20, force_groups=0):
        """Process lyrics text into groups with width control
        Args:
            lyrics_text: str, lyrics text to process
            max_width: int, maximum width of each line
            force_groups: int, force specific number of groups
        Returns:
            list: List of lyrics groups
        """
        # Calculate total length of lyrics
        total_length = len(lyrics_text)

        # Determine number of groups
        if force_groups > 0:
            num_groups = force_groups
        else:
            # Default to groups of roughly 500 characters
            num_groups = (total_length + 499) // 500  # Ceiling division

        # Calculate target size per group
        target_group_size = total_length / num_groups if num_groups > 0 else 0

        # Split lyrics into lines and remove empty lines
        lyrics_lines = [line.strip() for line in lyrics_text.split('\n') if line.strip()]

        if not lyrics_lines:
            return []

        # First pass: combine adjacent lines within max_width
        combined_lines = []
        current_line = lyrics_lines[0]

        for next_line in lyrics_lines[1:]:
            # Try combining with next line (including a space between)
            combined = current_line + " " + next_line
            if len(combined) <= max_width:
                current_line = combined
            else:
                combined_lines.append(current_line)
                current_line = next_line

        # Add the last line
        combined_lines.append(current_line)

        # Second pass: group lines with balanced length
        groups = []
        current_group = []
        current_length = 0

        for line in combined_lines:
            line_length = len(line) + 1  # +1 for newline
            new_length = current_length + line_length

            # Check if adding this line would make the group too far from target size
            if (current_length > 0 and  # Don't check first line
                    abs(new_length - target_group_size) > abs(current_length - target_group_size) and
                    len(groups) < num_groups - 1):  # Don't create new group if we're on last group
                groups.append('\n'.join(current_group))
                current_group = [line]
                current_length = len(line)
            else:
                current_group.append(line)
                current_length = new_length

        # Add the last group
        if current_group:
            groups.append('\n'.join(current_group))

        return groups

    async def process(self, message_info, parameters):
        # Get lyrics of current song
        # Parse parameters
        force_groups = 0
        params = parameters

        if params:
            try:
                # Try to parse first parameter as group number
                force_groups = int(params[0])
                # Remove group number from query
                query = ' '.join(params[1:])
            except ValueError:
                # First parameter is not a number, use entire query
                query = ' '.join(params)
        else:
            query = ""

        result = self.query_lyrics(query, force_groups)
        if 'error' in result:
            return result

        groups = result['groups']
        l = 0
        for lyr in groups:
            l += len(lyr)
            self.soul_handler.send_message(lyr)

        prompt = f' {len(groups)} piece(s) of lyrics sent, {l} characters'
        # Send lyrics back to Soul using command's template
        return {
            'lyrics': prompt
        }
