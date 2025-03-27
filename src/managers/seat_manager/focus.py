import re
from .base import SeatManagerBase

class FocusManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.previous_focus_count = None

    def update(self):
        """Update focus count"""
        if self.handler is None:
            return
        self.check_focus_count()

    def check_focus_count(self):
        """Check the focus count"""
        if self.handler is None:
            return
            
        focus_count_element = self.handler.try_find_element_plus('focus_count', log=False)
        if not focus_count_element:
            return

        current_focus_count_text = focus_count_element.text
        match = re.search(r'(\d+)人专注中', current_focus_count_text)
        if not match:
            return

        current_focus_count = int(match.group(1))
        if self.previous_focus_count == current_focus_count:
            return

        self.previous_focus_count = current_focus_count
        self.handler.logger.info(f"Focus count changed to: {current_focus_count}") 