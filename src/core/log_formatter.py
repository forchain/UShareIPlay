"""Custom log formatter with color support and abbreviated level markers"""
import logging


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support and short level names"""
    
    # ANSI color codes
    COLORS = {
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[91m', # Red
        'RESET': '\033[0m'      # Reset
    }
    
    # Short level names mapping
    LEVEL_NAMES = {
        'DEBUG': 'D',
        'INFO': 'I',
        'WARNING': 'W',
        'ERROR': 'E',
        'CRITICAL': 'C'
    }
    
    def __init__(self, fmt=None, datefmt=None, use_colors=False):
        """
        Initialize formatter
        
        Args:
            fmt: Log format string
            datefmt: Date format string
            use_colors: Whether to apply ANSI colors to console output
        """
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors
    
    def format(self, record):
        """Format log record with short level name and optional colors"""
        # Replace levelname with short version
        original_levelname = record.levelname
        record.levelname = self.LEVEL_NAMES.get(original_levelname, original_levelname)
        
        # Format the message
        formatted = super().format(record)
        
        # Apply colors if enabled and level requires it
        if self.use_colors and original_levelname in self.COLORS:
            color = self.COLORS[original_levelname]
            reset = self.COLORS['RESET']
            formatted = f"{color}{formatted}{reset}"
        
        # Restore original levelname for other handlers
        record.levelname = original_levelname
        
        return formatted

