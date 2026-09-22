"""A simulated Soul party seat panel for seat-management tests.

Models the parts of the real Appium surface that seat automation touches: the six
desk containers, the left/right seat + state + label children, the expand/collapse
button, and the user profile popup opened by clicking a seat state element.

Popup clicks are counted separately from seat clicks because the differential
probe's cost is measured in profile popups, not swipes.

Also carries the helpers the seat tests share for reading a logged Seat Roster.
"""

from types import SimpleNamespace

OWNER_LABEL = "群主"


def change_rows(message):
    """The transition summary of one logged Seat Roster, as token lists."""
    return [line.strip("│ ").split() for line in message.splitlines() if "➔" in line]


class FakeElement:
    def __init__(self, text="", *, on_click=None):
        self.text = text
        self.clicked = 0
        self.size = {"height": 10, "width": 10}
        self.location = {"x": 0, "y": 0}
        self._on_click = on_click

    def click(self):
        self.clicked += 1
        if self._on_click is not None:
            self._on_click()


class FakeDesk:
    """Attribute names mirror the config element keys read by ``read_desk``."""

    def __init__(self, index):
        self.index = index
        self.left_seat = FakeElement()
        self.right_seat = FakeElement()
        self.left_state = FakeElement()
        self.right_state = FakeElement()
        self.left_label = FakeElement()
        self.right_label = FakeElement()
        self.size = {"height": 10, "width": 10}
        self.location = {"x": 0, "y": 0}


class FakeSeatPanel:
    """Seat panel state: who sits where, plus the UI signals derived from it."""

    def __init__(
        self,
        occupants=None,
        *,
        owner_seats=(),
        popup_names=None,
        popup_failures=(),
        seats_expanded=False,
    ):
        self.occupants = {int(k): v for k, v in (occupants or {}).items()}
        self.owner_seats = {int(seat) for seat in owner_seats}
        self.popup_names = {int(k): v for k, v in (popup_names or {}).items()}
        self.popup_failures = {int(seat) for seat in popup_failures}
        self.seats_expanded = seats_expanded

        self.desks = [FakeDesk(index) for index in range(6)]
        #: Optional callback fired as a profile popup opens, so a test can make
        #: the panel change underneath an in-flight interaction.
        self.on_popup = None
        self.opened_popup = None
        self.popup_clicks = 0
        self.press_backs = 0
        self.scrolls = []
        self.swipes = []
        self.expand_clicks = 0
        self.collapse_clicks = 0
        self.expand_button = FakeElement(on_click=self.toggle_seats)
        self._sync_expand_button()
        self.handler = FakeSeatHandler(self)
        self.refresh()

    def toggle_seats(self):
        """Clicking the panel handle flips the expanded state."""
        self.seats_expanded = not self.seats_expanded
        if self.seats_expanded:
            self.expand_clicks += 1
        else:
            self.collapse_clicks += 1
        self._sync_expand_button()

    def _sync_expand_button(self):
        self.expand_button.text = "收起座位" if self.seats_expanded else "展开座位"

    # --- panel state -------------------------------------------------

    def seat_number_of(self, desk_index, side):
        return desk_index * 2 + (1 if side == "left" else 2)

    def desk_index_of(self, seat_number):
        return (seat_number - 1) // 2

    def side_of(self, seat_number):
        return "left" if seat_number % 2 else "right"

    def set_occupant(self, seat_number, username):
        self.occupants[int(seat_number)] = username
        self.refresh()

    def clear_seat(self, seat_number):
        self.occupants.pop(int(seat_number), None)
        self.refresh()

    def refresh(self):
        for desk in self.desks:
            for side in ("left", "right"):
                seat_number = self.seat_number_of(desk.index, side)
                occupied = seat_number in self.occupants
                state = getattr(desk, f"{side}_state")
                seat = getattr(desk, f"{side}_seat")
                label = getattr(desk, f"{side}_label")
                state._on_click = (
                    lambda seat_number=seat_number: self.open_popup(seat_number)
                )
                # Tapping an occupied seat opens its profile; an empty one starts
                # the take-a-seat flow instead.
                seat._on_click = (
                    (lambda seat_number=seat_number: self.open_popup(seat_number))
                    if occupied
                    else None
                )
                if seat_number in self.owner_seats:
                    label.text = OWNER_LABEL
                else:
                    label.text = str(seat_number)

    @property
    def occupancy_mask(self):
        return tuple(
            self.seat_number_of(desk.index, side) in self.occupants
            for desk in self.desks
            for side in ("left", "right")
        )

    # --- popup -------------------------------------------------------

    def open_popup(self, seat_number):
        self.popup_clicks += 1
        if seat_number in self.popup_failures:
            self.opened_popup = None
        else:
            self.opened_popup = self.popup_names.get(
                seat_number, self.occupants.get(seat_number)
            )
        if self.on_popup is not None:
            self.on_popup(seat_number)

    def press_back(self):
        self.press_backs += 1
        self.opened_popup = None

    def is_seat_occupied(self, desk, key):
        side = key.split("_")[0]
        seat_number = self.seat_number_of(desk.index, side)
        return seat_number in self.occupants


class _Logger:
    def __init__(self):
        self.records = []

    def _log(self, level):
        def record(message):
            self.records.append((level, message))

        return record

    def __getattr__(self, level):
        return self._log(level)


class _ElementFinder:
    def __init__(self, panel):
        self.panel = panel

    def find_elements(self, key):
        assert key == "seat_desk"
        return self.panel.desks

    def try_find_element(self, key, log=False):
        if key == "expand_seats":
            return self.panel.expand_button
        if key == "souler_name":
            return FakeElement(self.panel.opened_popup or "")
        return None

    def find_child_element(self, desk, key, log_failure=True):
        if not hasattr(desk, key):
            return None
        if key.endswith("_seat"):
            return getattr(desk, key)
        if self.panel.is_seat_occupied(desk, key):
            return getattr(desk, key)
        return None

    def wait_for_any_element(self, keys):
        if self.panel.opened_popup:
            return keys[0], FakeElement(self.panel.opened_popup)
        return keys[0], None

    def wait_for_element_clickable(self, key, timeout=0):
        if key == "confirm_seat":
            return FakeElement("确定")
        if key == "seat_off":
            return FakeElement("抱下")
        if key == "bottom_drawer":
            return None
        return None


class _KeyActions:
    def __init__(self, panel):
        self.panel = panel

    def press_back(self):
        self.panel.press_back()


class _GestureHandler:
    def __init__(self, panel):
        self.panel = panel

    def swipe(self, *args, **kwargs):
        self.panel.swipes.append(args)

    def click_element_at(self, element, *args, **kwargs):
        return None


class FakeSeatHandler:
    def __init__(self, panel):
        self.panel = panel
        self.logger = _Logger()
        self.errors = []
        self.element_finder = _ElementFinder(panel)
        self.key_actions = _KeyActions(panel)
        self.gesture_handler = _GestureHandler(panel)
        self.driver = SimpleNamespace(swipe=self.gesture_handler.swipe)
        self.controller = None

    def log_error(self, message):
        self.errors.append(message)

    def find_elements(self, key):
        return self.element_finder.find_elements(key)


def make_panel(occupants=None, **kwargs):
    """Build a panel plus the ``seat_desks`` list callers pass to the probe."""
    panel = FakeSeatPanel(occupants, **kwargs)
    return panel, panel.desks
