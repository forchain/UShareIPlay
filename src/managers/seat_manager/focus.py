import re
from .base import SeatManagerBase
from .seating import SeatingManager

class FocusManager(SeatManagerBase):
    def __init__(self, handler=None):
        super().__init__(handler)
        self.previous_focus_count = None
        self.seating = SeatingManager(handler)

    def update(self):
        """Update focus count"""
        if self.handler is None:
            return
        self.check_focus_count()

    def check_focus_count(self, force_check: bool = False):
        """
        Check the focus count
        
        Args:
            force_check: If True, force check even if count hasn't changed (useful after party creation)
        """
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
        if not force_check and self.previous_focus_count == current_focus_count:
            return

        self.previous_focus_count = current_focus_count
        self.seating.find_owner_seat()
        self.handler.logger.info(f"Focus count changed to: {current_focus_count}")
    
    def reset_and_check(self):
        """
        Reset previous count and check focus count (useful after party creation)
        This simulates a seat count change event by resetting the previous count
        """
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
        # Set previous count to current - 1 to simulate a change event
        # This ensures the check will trigger the seat change logic
        self.previous_focus_count = current_focus_count - 1 if current_focus_count > 0 else None
        self.check_focus_count(force_check=False) 