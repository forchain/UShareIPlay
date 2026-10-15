from ushareiplay.core.base_command import BaseCommand
from datetime import datetime, timedelta
from langdetect import detect_langs
import langdetect

# 在导入后设置种子
langdetect.DetectorFactory.seed = 0


def wrap_line_at_spaces(line: str, max_width: int) -> str:
    """Insert newlines so each segment fits max_width, preferring breaks at whitespace.

    English words stay intact when possible (break after last space before the limit).
    When no space exists in the window (long word or unspaced CJK), breaks at max_width.
    """
    line = line.strip()
    if not line or max_width <= 0:
        return line
    if len(line) <= max_width:
        return line
    out = []
    remaining = line
    while len(remaining) > max_width:
        chunk = remaining[:max_width]
        break_at = -1
        for i in range(len(chunk) - 1, 0, -1):
            if chunk[i].isspace():
                break_at = i
                break
        if break_at > 0:
            out.append(remaining[:break_at].rstrip())
            remaining = remaining[break_at:].lstrip()
        else:
            out.append(remaining[:max_width])
            remaining = remaining[max_width:].lstrip()
    if remaining:
        out.append(remaining)
    return "\n".join(out)


class LyricsCommand(BaseCommand):
    # 派发走 Soul 公屏，`message_dispatch` 绑定的是 soul_handler
    handler_attr = 'soul_handler'

    def query_lyrics(self, query, group_num=0):
        """取歌词并按房间里的排版约定分组。

        取歌词本身是 `MusicManager` 背后的 UI 接缝的事（#430）：切前台、查歌、
        切歌词 tab、读 DOM、解 HTML 实体都在那边，这里一个 UI 动作都不做。

        Args:
            query: str, 歌词搜索词；空串表示「问当前正在放的这首」
            group_num: int, number of groups to force
        Returns:
            dict: `{'groups': [...]}` 或 `{'error': ...}`（原样透出接缝的错误）
        """
        result = self.music_manager.query_lyrics(query) or {}
        if 'error' in result:
            return result

        lyrics_content = result.get('lyrics', '')

        lyrics_cfg = (self.controller.config or {}).get("lyrics") or {}
        line_max_width = int(lyrics_cfg.get("line_max_width", 18))

        lyrics_groups = self.process_lyrics(
            lyrics_content,
            max_width=line_max_width,
            force_groups=group_num,
        )
        return {'groups': lyrics_groups}

    def process_lyrics(
        self,
        lyrics_text,
        max_width=18,
        force_groups=0,
    ):
        """Process lyrics text into groups with width control
        Args:
            lyrics_text: str, lyrics text to process
            max_width: int, max characters per visual line (wrap at spaces when possible)
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

        # Per source line: only split when longer than display width (prefer breaks at spaces)
        wrapped_lines = []
        for line in lyrics_lines:
            wrapped = wrap_line_at_spaces(line, max_width)
            wrapped_lines.extend(
                [seg for seg in wrapped.split("\n") if seg.strip()]
            )

        # Group lines with balanced length
        groups = []
        current_group = []
        current_length = 0

        for line in wrapped_lines:
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

    async def do_process(self, message_info, parameters):
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
            self.message_dispatch.send_screen_message(lyr)

        prompt = f' {len(groups)} piece(s) of lyrics sent, {l} characters'
        # Send lyrics back to Soul using command's template
        return {
            'lyrics': prompt
        }
