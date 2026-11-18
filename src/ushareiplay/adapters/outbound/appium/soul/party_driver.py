"""生产适配器：把 Soul App 派对建房、退房、切房与恢复的 Appium 操作封装在 PartyDriverPort 之后。"""

import logging
from typing import Any, Optional

from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

from ushareiplay.modules.room.ports import PartyDriverPort


class SoulPartyDriver(PartyDriverPort):
    """基于 SoulHandler 的派对 UI 驱动。"""

    def __init__(self, handler=None):
        self._handler = handler
        self._logger = getattr(handler, "logger", None)

    @property
    def handler(self):
        return self._handler

    @property
    def logger(self):
        if self._logger is None:
            self._logger = getattr(self._handler, "logger", None) or logging.getLogger("PartyManager")
        return self._logger

    def get_party_id(self) -> Optional[str]:
        if self._handler is None:
            return None
        return self._handler.party_id

    def set_party_id(self, party_id: Optional[str]) -> None:
        if self._handler is not None:
            self._handler.party_id = party_id

    def end_party_ui(self) -> dict:
        if not self.handler.key_actions.switch_to_app():
            return {'error': 'Failed to switch to Soul app'}
        self.logger.info("Switched to Soul app")

        exit_room_btn = self.handler.element_finder.try_find_element('exit_room_btn', log=False)
        if exit_room_btn:
            exit_room_btn.click()
            self.logger.info("Clicked exit room button directly")
        else:
            self.logger.info("Direct exit room button not found, trying more menu...")
            more_menu = self.handler.element_finder.wait_for_element_clickable('more_menu')
            if not more_menu:
                return {'error': 'Failed to find more menu'}
            more_menu.click()
            self.logger.info("Clicked more menu")

            end_party = self.handler.element_finder.wait_for_element_clickable('end_party')
            if not end_party:
                return {'error': 'Failed to find end party option'}
            end_party.click()
            self.logger.info("Clicked end party option")

        confirm_end = self.handler.element_finder.wait_for_element_clickable('confirm_end', timeout=3)
        if confirm_end:
            confirm_end.click()
            self.logger.info("Clicked confirm end button")
        else:
            self.logger.info("No confirm button found, proceeding directly")

        return {'success': 'Party ended'}

    def restore_current_party(self) -> bool:
        try:
            keys = ['private_room_entry', 'floating_entry', 'party_back']
            key, element = self.handler.element_finder.wait_for_any_element(keys, timeout=2)
            if element:
                element.click()
                self.logger.info(f"Restored current party via {key}")
                return True

            search_back = self.handler.element_finder.try_find_element('search_back', log=False)
            if search_back:
                search_back.click()
                self.logger.info("Clicked search_back before restoring party")
            elif hasattr(self.handler.key_actions, 'press_back'):
                self.handler.key_actions.press_back()

            key, element = self.handler.element_finder.wait_for_any_element(keys, timeout=2)
            if element:
                element.click()
                self.logger.info(f"Restored current party via {key} after back")
                return True

            self.logger.warning("未能找到恢复派对的悬浮窗入口")
            return False
        except Exception as e:
            self.logger.warning(f"Error restoring current party: {e}")
            return False

    def minimize_room(self) -> bool:
        minimize_btn = self.handler.element_finder.try_find_element('minimize_room', log=False)
        if not minimize_btn:
            return False
        minimize_btn.click()
        self.logger.info("Clicked minimize_room button (ivChatZoomIn)")
        return True

    def navigate_to_hall_entry(self) -> bool:
        if self.handler.element_finder.try_find_element('search_entry', log=False):
            return True
        if self._navigate_back_to_hall_entry():
            return True
        more_menu = self.handler.element_finder.try_find_element('more_menu', log=False)
        if more_menu:
            more_menu.click()
            self.logger.info("Clicked more menu button as fallback")
            self.handler.element_finder.wait_for_element('more_menu_container')
            party_hall = self.handler.element_finder.wait_for_element_clickable('party_hall')
            if party_hall:
                party_hall.click()
                self.logger.info("Clicked party hall entry from more menu")
                return True
        return False

    def _navigate_back_to_hall_entry(self, max_attempts: int = 5) -> bool:
        for attempt in range(max_attempts):
            if self.handler.element_finder.try_find_element('search_entry', log=False):
                self.logger.info("Already at search entry")
                return True

            if self.enter_party_hall_from_home():
                if self.handler.element_finder.wait_for_element_clickable('search_entry'):
                    self.logger.info("Successfully entered party hall from home")
                    return True

            party_hall_entry = self.handler.element_finder.try_find_element('party_hall_entry', log=False)
            if party_hall_entry:
                party_hall_entry.click()
                self.logger.info("Clicked party_hall_entry directly")
                if self.handler.element_finder.wait_for_element_clickable('search_entry'):
                    return True

            self.logger.info(f"Navigating back to find hall entry (attempt {attempt + 1}/{max_attempts})")
            back_keys = [
                'item_left_back', 'titlebar_back_ivbtn', 'go_back', 'go_back_1',
                'h5_back', 'group_back', 'close_button', 'close_btn', 'activity_back',
            ]
            back_key, back_elem = self.handler.element_finder.wait_for_any_element(back_keys, timeout=1)
            if back_elem:
                back_elem.click()
                self.logger.info(f"Clicked back button: {back_key}")
            elif hasattr(self.handler.key_actions, 'press_back'):
                self.handler.key_actions.press_back()
                self.logger.info("Pressed system back key")

        if self.enter_party_hall_from_home():
            return bool(self.handler.element_finder.wait_for_element_clickable('search_entry'))
        return bool(self.handler.element_finder.try_find_element('search_entry', log=False))

    def search_party(self, party_id: str) -> bool:
        search_entry = self.handler.element_finder.wait_for_element_clickable('search_entry')
        if not search_entry:
            return False
        search_entry.click()
        self.logger.info("Clicked search entry")

        search_box = self.handler.element_finder.wait_for_element_clickable('search_box')
        if not search_box:
            return False
        search_box.send_keys(party_id)
        self.logger.info(f"Entered party ID: {party_id}")

        search_button = self.handler.element_finder.wait_for_element_clickable('search_button')
        if not search_button:
            return False
        search_button.click()
        self.logger.info("Clicked search button")
        return True

    def _check_target_party_online(self) -> tuple[Optional[Any], Optional[Any]]:
        key, result_element = self.handler.element_finder.wait_for_any_element(
            ['party_online', 'room_card', 'parties_search', 'party_search_empty', 'no_party_from_hall'],
            timeout=5,
        )

        room_card = self.handler.element_finder.try_find_element('room_card', log=False)
        if not room_card:
            if key == 'parties_search' and result_element:
                room_card = (
                    self.handler.element_finder.find_child_element(result_element, 'party_id')
                    or self.handler.element_finder.find_child_element(result_element, 'room_card')
                    or result_element
                )
            elif key in ('party_online', 'room_card') and result_element:
                room_card = result_element

        party_online = self.handler.element_finder.try_find_element('party_online', log=False)
        if not party_online:
            if key == 'party_online' and result_element:
                party_online = result_element
            elif key == 'parties_search' and result_element:
                party_online = (
                    self.handler.element_finder.find_child_element(result_element, 'party_online')
                    or self.handler.element_finder.find_child_element(result_element, 'party_id')
                )

        return room_card, party_online

    def is_target_party_online(self) -> bool:
        room_card, party_online = self._check_target_party_online()
        return bool(room_card and party_online)

    def enter_searched_party(self) -> bool:
        room_card = self.handler.element_finder.wait_for_element_clickable('room_card')
        if not room_card:
            room_card, _ = self._check_target_party_online()

        if not room_card:
            return False

        room_card.click()
        self.logger.info("Clicked room_card to enter target party")

        confirm_btn = self.handler.element_finder.wait_for_element_clickable('confirm_end', timeout=2)
        if confirm_btn:
            confirm_btn.click()
            self.logger.info("Confirmed room switch dialog")

        self.handler.grab_mic_and_confirm()
        return True

    def _click_element_safe(self, element, key: str = None) -> bool:
        try:
            if element:
                element.click()
                return True
        except (StaleElementReferenceException, WebDriverException) as e:
            self.logger.warning(
                f"Element {key} click stale or failed, retrying with wait_for_element_clickable: {e}"
            )
            if key and hasattr(self.handler, 'element_finder'):
                retry_elem = self.handler.element_finder.wait_for_element_clickable(key, timeout=3)
                if retry_elem:
                    try:
                        retry_elem.click()
                        return True
                    except Exception as retry_e:
                        self.logger.warning(f"Retry click failed for {key}: {retry_e}")
        except Exception as e:
            self.logger.warning(f"Failed to click element {key}: {e}")
        return False

    def click_visible_party_back(self) -> bool:
        party_back_elem = self.handler.element_finder.try_find_element('party_back', log=False)
        if party_back_elem and self._click_element_safe(party_back_elem, 'party_back'):
            self.logger.info("Clicked back to party (dialog was already visible)")
            return True
        return False

    def enter_party_hall_from_home(self) -> bool:
        planet_tab = self.handler.element_finder.try_find_element('planet_tab', log=False)
        if not planet_tab:
            return False
        self.logger.info("发现首页，尝试进入派对")
        planet_tab.click()

        party_hall_entry = self.handler.element_finder.wait_for_element_clickable('party_hall_entry')
        if not party_hall_entry:
            self.logger.warning("未找到派对大厅入口")
            return False
        party_hall_entry.click()
        self.logger.info("Clicked party hall entry")
        return True

    def try_enter_existing_party(self, party_id: Optional[str]) -> bool:
        key, element = self.handler.element_finder.wait_for_any_element(['party_back', 'search_entry'])
        if not element:
            self.logger.warning("未找到派对入口")
            return False

        if key == 'party_back':
            if self._click_element_safe(element, 'party_back'):
                self.logger.info("Clicked back to party")
                return True
            return False

        if not self._click_element_safe(element, 'search_entry'):
            self.logger.warning("点击搜索入口失败")
            return False
        self.logger.info("Clicked search entry")
        search_box = self.handler.element_finder.wait_for_element('search_box')
        if not search_box:
            party_back = self.handler.element_finder.try_find_element('party_back', log=False)
            if party_back and self._click_element_safe(party_back, 'party_back'):
                self.logger.info("Clicked back to party (found party_back after search entry)")
                return True
            self.logger.warning("未找到搜索框")
            return False

        if not party_id:
            self.logger.warning("未配置 default_party_id，直接准备创建派对")
            self._go_back_from_search()
            return False

        search_box.send_keys(party_id)
        self.logger.info(f"Entered party ID: {party_id}")
        search_button = self.handler.element_finder.wait_for_element('search_button')
        if not search_button:
            self.logger.warning("未找到搜索按钮")
            return False
        search_button.click()
        self.logger.info("Clicked search button")

        room_card = self.handler.element_finder.wait_for_element('room_card')
        if not room_card:
            self.logger.warning("未找到派对房间，视为派对关闭，准备重建派对")
            self._go_back_from_search()
            return False

        party_online = self.handler.element_finder.try_find_element('party_online')
        if party_online:
            room_card.click()
            self.logger.info("Clicked room card")
            return True

        self.logger.warning("派对关闭了")
        self._go_back_from_search()
        return False

    def _go_back_from_search(self) -> None:
        search_back = self.handler.element_finder.wait_for_element('search_back')
        if search_back:
            search_back.click()
            self.logger.info("Clicked search back")
            return
        self.logger.warning("未找到搜索返回按钮，尝试系统返回")
        self.handler.key_actions.press_back()

    def create_party_flow(
        self,
        *,
        mode: str,
        recommendation_enabled: bool,
        change_party_type: bool,
        target_party_type_element: str,
    ) -> tuple[bool, Optional[bool]]:
        party_back = self.handler.element_finder.try_find_element('party_back', log=False)
        if party_back and self._click_element_safe(party_back, 'party_back'):
            self.logger.info("Clicked back to party in create_party_flow")
            return True, None

        key, element = self.handler.element_finder.wait_for_any_element(
            ['create_party_entry', 'create_room_entry']
        )
        if not element:
            party_back = self.handler.element_finder.try_find_element('party_back', log=False)
            if party_back and self._click_element_safe(party_back, 'party_back'):
                self.logger.info("Clicked back to party (found party_back after create party timeout)")
                return True, None
            self.logger.warning("未找到派对入口")
            return False, None
        if not self._click_element_safe(element, key):
            self.logger.warning(f"点击派对创建入口 {key} 失败")
            return False, None
        self.logger.info("Clicked create party entry")

        if mode == 'restore_party':
            wait_keys = ['restore_party', 'confirm_party', 'party_state_entry']
        else:
            wait_keys = ['new_party_entry', 'confirm_party', 'party_state_entry']
        key, element = self.handler.element_finder.wait_for_any_element(wait_keys)
        if not element:
            self.logger.warning("未找到派对创建或恢复按钮")
            return False, None

        if key == 'restore_party':
            element.click()
            self.logger.info("Clicked restore party entry")
            return True, None

        if key in ('new_party_entry', 'confirm_party'):
            element.click()
            self.logger.info(f"Clicked new party entry: {key}")

        actual_recommendation: Optional[bool]
        if not recommendation_enabled:
            party_state_entry = (
                element
                if key == 'party_state_entry'
                else self.handler.element_finder.wait_for_element('party_state_entry')
            )
            if not party_state_entry:
                self.logger.warning("未找到派对状态入口按钮")
                return False, None
            party_state_entry.click()
            self.logger.info("Clicked party state entry to disable recommendation")
            close_party_notification = self.handler.element_finder.wait_for_element(
                'close_party_notification'
            )
            if not close_party_notification:
                self.logger.warning("未找到关闭派对推荐")
                return False, None
            close_party_notification.click()
            self.logger.info("Clicked close party notification")
            if hasattr(self.handler.element_finder, 'wait_for_element_disappear'):
                self.handler.element_finder.wait_for_element_disappear(
                    'close_party_notification', timeout=2.0
                )
            actual_recommendation = False
        else:
            self.logger.info("Keep party recommendation enabled as configured (default '所有人')")
            actual_recommendation = True

        if change_party_type:
            party_type_target = None
            for attempt in range(3):
                party_type_chat = (
                    self.handler.element_finder.wait_for_element_clickable('party_type_chat', timeout=3)
                    if hasattr(self.handler.element_finder, 'wait_for_element_clickable')
                    else None
                )
                if not party_type_chat:
                    party_type_chat = self.handler.element_finder.wait_for_element('party_type_chat')
                if not party_type_chat:
                    self.logger.warning("未找到闲聊唠嗑派对类型按钮")
                    return False, None

                party_type_chat.click()
                self.logger.info(f"Clicked party type chat entry (闲聊唠嗑) (attempt {attempt + 1})")

                party_type_target = self.handler.element_finder.wait_for_element(
                    target_party_type_element, timeout=3
                )
                if party_type_target:
                    party_type_target.click()
                    self.logger.info(f"Clicked target party type entry ({target_party_type_element})")
                    if hasattr(self.handler.element_finder, 'wait_for_element_disappear'):
                        self.handler.element_finder.wait_for_element_disappear(
                            target_party_type_element, timeout=2.0
                        )
                    break
                self.logger.warning(
                    f"未在弹窗中找到目标派对类型按钮 ({target_party_type_element})，准备重试点击类型入口..."
                )

            if not party_type_target:
                self.logger.warning(f"未找到目标派对类型按钮: {target_party_type_element}")
                return False, None
        else:
            self.logger.info("Skip changing party type during creation (change_party_type=False)")

        create_party_button = (
            self.handler.element_finder.wait_for_element_clickable('create_party_button', timeout=5)
            if hasattr(self.handler.element_finder, 'wait_for_element_clickable')
            else None
        )
        if not create_party_button:
            create_party_button = self.handler.element_finder.wait_for_element('create_party_button')
        if not create_party_button:
            self.logger.warning("未找到创建房间按钮")
            return False, None
        create_party_button.click()
        self.logger.info("Clicked create party button")
        return True, actual_recommendation
