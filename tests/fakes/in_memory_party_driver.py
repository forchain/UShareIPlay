from typing import Optional

from ushareiplay.modules.room.ports import PartyDriverPort


class InMemoryPartyDriver(PartyDriverPort):
    """派对 UI 端口的内存替身，用于在不依赖 Appium 的情况下验证 PartyService 编排。"""

    def __init__(
        self,
        *,
        end_result: Optional[dict] = None,
        party_id: Optional[str] = None,
        online_parties: Optional[set[str]] = None,
        search_succeeds: bool = True,
        navigate_succeeds: bool = True,
        enter_searched_succeeds: bool = True,
        party_back_visible: bool = False,
        home_hall_succeeds: bool = False,
        existing_party_entered: bool = False,
        create_result: tuple[bool, Optional[bool]] = (True, True),
    ):
        self.end_result = end_result if end_result is not None else {'success': 'Party ended'}
        self.party_id = party_id
        self.online_parties = set(online_parties or ())
        self.search_succeeds = search_succeeds
        self.navigate_succeeds = navigate_succeeds
        self.enter_searched_succeeds = enter_searched_succeeds
        self.party_back_visible = party_back_visible
        self.home_hall_succeeds = home_hall_succeeds
        self.existing_party_entered = existing_party_entered
        self.create_result = create_result
        self.calls: list[tuple] = []
        self.last_searched_id: Optional[str] = None

    def end_party_ui(self) -> dict:
        self.calls.append(('end_party_ui',))
        return dict(self.end_result)

    def restore_current_party(self) -> bool:
        self.calls.append(('restore_current_party',))
        return True

    def minimize_room(self) -> bool:
        self.calls.append(('minimize_room',))
        return True

    def navigate_to_hall_entry(self) -> bool:
        self.calls.append(('navigate_to_hall_entry',))
        return self.navigate_succeeds

    def search_party(self, party_id: str) -> bool:
        self.calls.append(('search_party', party_id))
        self.last_searched_id = party_id
        return self.search_succeeds

    def is_target_party_online(self) -> bool:
        self.calls.append(('is_target_party_online',))
        return self.last_searched_id in self.online_parties

    def enter_searched_party(self) -> bool:
        self.calls.append(('enter_searched_party',))
        return self.enter_searched_succeeds

    def click_visible_party_back(self) -> bool:
        self.calls.append(('click_visible_party_back',))
        return self.party_back_visible

    def enter_party_hall_from_home(self) -> bool:
        self.calls.append(('enter_party_hall_from_home',))
        return self.home_hall_succeeds

    def try_enter_existing_party(self, party_id: Optional[str]) -> bool:
        self.calls.append(('try_enter_existing_party', party_id))
        return self.existing_party_entered

    def create_party_flow(
        self,
        *,
        mode: str,
        recommendation_enabled: bool,
        change_party_type: bool,
        target_party_type_element: str,
    ) -> tuple[bool, Optional[bool]]:
        self.calls.append(
            (
                'create_party_flow',
                mode,
                recommendation_enabled,
                change_party_type,
                target_party_type_element,
            )
        )
        return self.create_result

    def get_party_id(self) -> Optional[str]:
        return self.party_id

    def set_party_id(self, party_id: Optional[str]) -> None:
        self.party_id = party_id
        self.calls.append(('set_party_id', party_id))
