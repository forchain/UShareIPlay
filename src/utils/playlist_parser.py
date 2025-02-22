class PlaylistParser:
    def __init__(self):
        # Define separators in order of priority
        self.separators = [
            '丨', '|',  # Vertical bars (full-width and half-width)
            '【', '】',  # Full-width square brackets
            '[', ']',   # Half-width square brackets
            '（', '）',  # Full-width parentheses
            '(', ')',   # Half-width parentheses
            '-', '—',   # Dashes (half-width and full-width)
            '·',        # Middle dot
            '/',        # Forward slash
            '、',       # Ideographic comma
            '：', ':',  # Colons (full-width and half-width)
        ]
        
        # Define characters to strip from subject and topic
        self.strip_chars = ''.join([
            ' ',        # Space
            '　',       # Full-width space
            '《', '》', # Full-width angle brackets
            '〈', '〉', # Full-width angle brackets (alternative)
            '「', '」', # Full-width corner brackets
            '『', '』', # Full-width white corner brackets
            '"', '"',   # Full-width quotation marks
            '"', '"',   # Half-width quotation marks
            ''', ''',   # Full-width single quotes
            "'", "'",   # Half-width single quotes
            '…',        # Ellipsis
            '～',       # Full-width tilde
            '~',        # Half-width tilde
            '♪',        # Music note
            '☆', '★',  # Stars
            '❤',       # Heart
        ])

    def parse_playlist_name(self, playlist_name: str) -> tuple:
        """
        Parse playlist name into subject and topic
        Args:
            playlist_name: str, name of the playlist
        Returns:
            tuple: (subject, topic) where:
                  subject is the main theme/subject of the playlist
                  topic is the specific topic/focus
        """
        if not playlist_name:
            return '', ''

        # Try each separator
        for sep in self.separators:
            # Skip if separator not in playlist name
            if sep not in playlist_name:
                continue
                
            # Split by separator
            parts = playlist_name.split(sep, 1)  # Split only on first occurrence
            if len(parts) != 2:
                continue
                
            # Clean up parts
            subject = parts[0].strip(self.strip_chars)
            topic = parts[1].strip(self.strip_chars)
            
            # Validate parts
            if len(subject) >= 2 and len(topic) >= 2:
                return subject, topic
        
        # If no valid separator found, return playlist name as subject
        return playlist_name.strip(self.strip_chars), ''
