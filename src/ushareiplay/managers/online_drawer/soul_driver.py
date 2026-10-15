"""生产适配器：把 `SoulHandler` 的 Appium 细节包成在线用户抽屉端口。

这里的每一步都是既有在线名单抓取已经做过的那一步，不是重新设计的交互：

- 打开是 `try_find_element('user_count')` + `click()`（旧
  `OnlineListScraper._scrape_online_user_names` 的原样两步）；
- 关闭是按 `online_users_close` -> `close_button` 顺序点 `ivClose`
  （旧 `_close_online_users_dialog` 的第一段，`#414` 之后已不再当抽屉点遮罩）；
- 滑动是在容器 `location`/`size` 算出的坐标里从 0.75 高度滑到 0.30 高度，
  算不出时回落到既有的固定坐标；时长 800ms，是旧实现为避免惯性飞滚特意调慢过的值。

刻意**不移植**旧实现里的 `press_back` 与遮罩点击两段兜底：盲按返回会误退出派对
房间（spec #426 问题陈述 #1），而 `ivClose` 已经是确定可用的手势。旧路径保持原样
不动，等 #440 收口时统一退役。

#435 追加的资料卡与私聊那几步同样不是新设计的交互，而是把旧 `UserManager` 的裸
Appium 调用原样搬进来：点头像的 `y_ratio=0.7`、私聊各步 5 秒、找返回入口 3 秒、以及
`item_left_back` 之后补一下标题栏返回，都是旧实现里真机调出来的既有值，逐字保留。

#438 追加的送礼那几步同理，也全部照抄旧 `UserManager.send_gift`：点 `send_gift` 进弹窗、
`wait_for_any_element(['give_gift', 'use_item'])` 判弹窗到没到位、`luck_item` 的文案按
`x` 拆件数、点「使用」之后 `wait_for_element('confirm_use')` 再 `.click()`（不是坐标点击）。
**唯一没有搬过来的是那两处 `key_actions.press_back()`**：旧实现在收不掉弹窗时盲按返回，
收掉的只是最上面那层，底下的资料卡与抽屉照样悬在屏幕上（spec #426 问题陈述 #1）。
这里改用 `GIFT_POPUP_CLOSE_KEYS` 里的页内 X，收不掉就如实 False 让调用方记警告。
"""

import asyncio
import re
from typing import Optional

from ushareiplay.managers.online_drawer.driver import (
    ADMIN_CONFIRM_CLOSE_KEYS,
    ADMIN_CONFIRM_KEYS,
    ADMIN_CONTROL_TIMEOUT,
    ADMIN_INVITE_KEY,
    AVATAR_CLICK_Y_RATIO,
    CLOSE_KEYS,
    DEFAULT_SCROLL_DURATION_MS,
    DEFAULT_SETTLE_TIMEOUT,
    END_OF_LIST_KEY,
    ENTRY_KEY,
    GIFT_ACTION_GIVE,
    GIFT_ACTION_KEYS,
    GIFT_ACTION_USE,
    GIFT_CONFIRM_KEY,
    GIFT_ENTRY_KEY,
    GIFT_ITEM_NAME_KEY,
    GIFT_POPUP_CLOSE_KEYS,
    GIFT_POPUP_TIMEOUT,
    GIFT_SOUL_POWER_KEY,
    ONLINE_CONTAINER_KEY,
    POST_SCROLL_SETTLE_SECONDS,
    PRIVATE_CHAT_BUTTON_KEY,
    PRIVATE_CHAT_TIMEOUT,
    PRIVATE_MESSAGE_INPUT_KEY,
    PRIVATE_MESSAGE_SEND_KEY,
    PROFILE_CARD_AVATAR_KEY,
    PROFILE_CARD_NICKNAME_KEY,
    PROFILE_CARD_TIMEOUT,
    ROOM_ENTRY_KEYS,
    ROOM_RETURN_TIMEOUT,
    ROW_CONTAINER_KEY,
    ROW_FOLLOW_STATE_KEY,
    ROW_NAME_KEY,
    SETTLE_SECONDS,
    TITLEBAR_BACK_KEY,
    MemberRow,
    OnlineDrawerDriverPort,
)


class SoulOnlineDrawerDriver(OnlineDrawerDriverPort):
    """驱动真实 Soul App 在线用户抽屉的生产适配器。

    Args:
        handler: 注入的 `SoulHandler`。`None` 时所有动作都以「App 不可用」的
            方式失败，而不是抛 AttributeError。
    """

    def __init__(self, handler=None):
        self._handler = handler

    async def is_open(self) -> bool:
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False
        try:
            return bool(finder.try_find_element(ONLINE_CONTAINER_KEY, log=False))
        except Exception:
            return False

    async def open(self, *, error_message: str) -> dict:
        handler = self._handler
        if handler is None:
            return {'error': error_message}
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return {'error': error_message}

        entry = finder.try_find_element(ENTRY_KEY, log=False)
        if not entry:
            return {'error': error_message}
        try:
            entry.click()
        except Exception as e:
            self._log_warning(f"点击 {ENTRY_KEY} 失败: {e}")
            return {'error': error_message}
        return {}

    async def close(self) -> bool:
        """按顺序点专门的 `ivClose` 关闭按钮；两个都点不到返回 False。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False

        for key in CLOSE_KEYS:
            try:
                close_btn = None
                if hasattr(finder, "wait_for_element_clickable"):
                    close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn and hasattr(finder, "try_find_element"):
                    close_btn = finder.try_find_element(key, log=False)

                if close_btn:
                    close_btn.click()
                    if hasattr(finder, "wait_for_element_disappear"):
                        finder.wait_for_element_disappear(
                            key, timeout=2.0, poll_frequency=0.1
                        )
                    return True
            except Exception as e:
                self._log_warning(f"查找/点击关闭按钮 {key} 出错: {e}")

        return False

    async def wait_for_settle(self, *, timeout: int = DEFAULT_SETTLE_TIMEOUT) -> bool:
        """等容器出现，并留出它渲染行内容所需的静默。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return False

        container = finder.wait_for_element(ONLINE_CONTAINER_KEY, timeout=timeout)
        if not container:
            return False
        # 容器在 dump 里不等于行已经渲染出来，紧接着读会读到空的列表。
        await asyncio.sleep(SETTLE_SECONDS)
        return True

    async def scroll_container(
        self, *, duration_ms: int = DEFAULT_SCROLL_DURATION_MS
    ) -> bool:
        """在容器内手指上滑，列表向下滚一页；滑完等列表停稳。"""
        handler = self._handler
        if handler is None:
            return False
        finder = getattr(handler, "element_finder", None)
        gesture = getattr(handler, "gesture_handler", None)
        if finder is None or gesture is None or not hasattr(gesture, "swipe"):
            return False

        container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
        swipe_x, start_y, end_y = self._swipe_geometry(container)

        try:
            if swipe_x is not None:
                ok = gesture.swipe(swipe_x, start_y, swipe_x, end_y, duration_ms=duration_ms)
            else:
                # 容器坐标读不出来时的固定回落位，与旧实现逐字一致。
                ok = gesture.swipe(500, 1500, 500, 900, duration_ms)
            if not ok:
                self._log_warning("在线用户列表滑动失败")
                return False
        except Exception as e:
            self._log_warning(f"滑动在线用户列表时出错: {e}")
            return False

        # 滑完必须等 RecyclerView 停稳，否则下一步读到的是滑动途中的画面。
        await asyncio.sleep(POST_SCROLL_SETTLE_SECONDS)
        return True

    async def find_member_row(self, visible_username: str) -> Optional[MemberRow]:
        handler = self._handler
        if handler is None:
            return None
        finder = getattr(handler, "element_finder", None)
        if finder is None:
            return None

        container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
        if not container:
            return None

        for row in finder.find_child_elements(container, ROW_CONTAINER_KEY):
            try:
                name_elem = finder.find_child_element(row, ROW_NAME_KEY)
                if not name_elem:
                    continue
                # 只按 UI 上显示的昵称匹配：canonical 名在这里永远不相等。
                if (name_elem.text or '') != visible_username:
                    continue
                follow_elem = finder.find_child_element(
                    row, ROW_FOLLOW_STATE_KEY, log_failure=False
                )
                return MemberRow(
                    visible_name=name_elem.text,
                    follow_state=follow_elem.text if follow_elem else None,
                )
            except Exception:
                # 单行读坏不影响继续找下一行（滑动过程中行会失效是常态）。
                continue

        return None

    async def read_online_count(self) -> Optional[int]:
        """读「N 人在线」控件里第一段数字。

        解析留在这里而不是引擎：`6人在线` / `在线 10 人` 这些文案是 App 的事，引擎
        只该拿到一个 int 或 None。旧实现在 `OnlineListScraper` 里用同一个正则解析，
        这里只是把它挪到它该在的层。
        """
        finder = self._finder()
        if finder is None:
            return None
        try:
            entry = finder.try_find_element(ENTRY_KEY, log=False)
            if not entry:
                return None
            text = getattr(entry, "text", None)
            if not text:
                return None
            match = re.search(r'(\d+)', text)
            if not match:
                return None
            return int(match.group(1))
        except Exception:
            # 人数只是对账的期望值，读不到不该让整次抓取失败。
            return None

    async def visible_member_rows(self) -> list:
        """整页已渲染的行，一次读回昵称与关注关系。

        「翻页判据是这一页有没有带来新的人」，所以整页读数是一次语义上的读取；
        逐行问端口会把同一页 dump 五十次，正是这段旧代码当初踩的坑。
        """
        finder = self._finder()
        if finder is None:
            return []
        try:
            container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
            if not container:
                return []

            rows = []
            for row in finder.find_child_elements(container, ROW_CONTAINER_KEY):
                try:
                    name_elem = finder.find_child_element(row, ROW_NAME_KEY)
                    if not name_elem:
                        continue
                    visible_name = name_elem.text
                    if not visible_name:
                        continue
                    follow_elem = finder.find_child_element(
                        row, ROW_FOLLOW_STATE_KEY, log_failure=False
                    )
                    rows.append(
                        MemberRow(
                            visible_name=visible_name,
                            follow_state=follow_elem.text if follow_elem else None,
                        )
                    )
                except Exception:
                    # 单行读坏跳过整行，不影响这一页剩下的行（滚动途中失效是常态）。
                    continue
            return rows
        except Exception:
            return []

    async def is_at_end(self) -> bool:
        """`no_more_data` 提示在不在**且显示着**。"""
        finder = self._finder()
        if finder is None:
            return False
        try:
            hint = finder.try_find_element(END_OF_LIST_KEY, log=False)
            if not hint:
                return False
            return bool(hint.is_displayed())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 资料卡与私聊（#435）
    # ------------------------------------------------------------------

    async def open_member_profile(self, visible_username: str) -> bool:
        finder = self._finder()
        if finder is None:
            return False

        row = self._find_row_element(finder, visible_username)
        if row is None:
            self._log_warning(f"在线用户抽屉里找不到 {visible_username} 那一行")
            return False

        try:
            row.click()
        except Exception as e:
            self._log_warning(f"点击 {visible_username} 的在线用户行失败: {e}")
            return False

        # 点了不算开：资料卡是弹出动画，不等它出现在页面上就往下走，下一步读到的还是
        # 抽屉那一帧，调用方会把「卡片没弹出来」误当成正常继续。
        if not self._wait_for_profile_card(finder):
            self._log_warning(f"点击 {visible_username} 后资料卡没有出现")
            return False
        return True

    async def is_profile_card_open(self) -> bool:
        finder = self._finder()
        if finder is None:
            return False
        try:
            card = finder.try_find_element(PROFILE_CARD_NICKNAME_KEY, log=False)
            return bool(card) and bool(card.is_displayed())
        except Exception:
            return False

    async def dismiss_profile_card(self) -> bool:
        finder = self._finder()
        if finder is None:
            return False
        if not await self.is_profile_card_open():
            # 本来就没有卡片悬着：已经在房间里了，这一步是幂等的。
            return True

        handler = self._handler
        gesture = getattr(handler, "gesture_handler", None) if handler else None
        if gesture is None or not hasattr(gesture, "click_element_at"):
            self._log_warning("缺少手势处理器，无法收起资料卡")
            return False

        # 卡片与抽屉共用 ivClose，所以这里复用抽屉的关闭键组而不是另找一套手势 ——
        # 这也顺带保证了这里永远不会出现盲按返回。
        for key in CLOSE_KEYS:
            try:
                close_btn = None
                if hasattr(finder, "wait_for_element_clickable"):
                    close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn and hasattr(finder, "try_find_element"):
                    close_btn = finder.try_find_element(key, log=False)
                if not close_btn:
                    continue
                if not gesture.click_element_at(close_btn):
                    self._log_warning(f"点击资料卡关闭按钮 {key} 失败")
                    continue
                # 关掉了不能就算数：必须确认卡片真的走了，否则调用方会把一张悬着的卡片
                # 当成已经收拾干净。
                if hasattr(finder, "wait_for_element_disappear"):
                    finder.wait_for_element_disappear(
                        PROFILE_CARD_NICKNAME_KEY, timeout=PROFILE_CARD_TIMEOUT, poll_frequency=0.1
                    )
                if not await self.is_profile_card_open():
                    return True
            except Exception as e:
                self._log_warning(f"收起资料卡时 {key} 出错: {e}")
        return False

    async def open_member_home(self) -> bool:
        finder = self._finder()
        handler = self._handler
        gesture = getattr(handler, "gesture_handler", None) if handler else None
        if finder is None or gesture is None or not hasattr(gesture, "click_element_at"):
            return False
        avatar = finder.wait_for_element_clickable(
            PROFILE_CARD_AVATAR_KEY, timeout=PRIVATE_CHAT_TIMEOUT
        )
        if not avatar:
            return False
        return bool(gesture.click_element_at(avatar, y_ratio=AVATAR_CLICK_Y_RATIO))

    async def open_private_chat_page(self) -> bool:
        finder = self._finder()
        if finder is None:
            return False
        chat_btn = finder.wait_for_element_clickable(
            PRIVATE_CHAT_BUTTON_KEY, timeout=PRIVATE_CHAT_TIMEOUT
        )
        if not chat_btn:
            return False
        try:
            chat_btn.click()
            return True
        except Exception as e:
            self._log_warning(f"点击私聊按钮失败: {e}")
            return False

    async def type_private_message(self, text: str) -> bool:
        finder = self._finder()
        if finder is None:
            return False
        input_box = finder.wait_for_element_clickable(
            PRIVATE_MESSAGE_INPUT_KEY, timeout=PRIVATE_CHAT_TIMEOUT
        )
        if not input_box:
            return False
        try:
            input_box.send_keys(text)
            return True
        except Exception as e:
            self._log_warning(f"在私聊输入框输入文字失败: {e}")
            return False

    async def submit_private_message(self) -> bool:
        finder = self._finder()
        if finder is None:
            return False
        send_button = finder.wait_for_element_clickable(
            PRIVATE_MESSAGE_SEND_KEY, timeout=PRIVATE_CHAT_TIMEOUT
        )
        if not send_button:
            return False
        try:
            send_button.click()
            return True
        except Exception as e:
            self._log_warning(f"点击私聊发送按钮失败: {e}")
            return False

    async def return_to_room(self) -> bool:
        finder = self._finder()
        if finder is None or not hasattr(finder, "wait_for_any_element"):
            return False
        try:
            _key, entry = finder.wait_for_any_element(
                list(ROOM_ENTRY_KEYS), timeout=ROOM_RETURN_TIMEOUT
            )
        except Exception as e:
            self._log_warning(f"找返回房间入口出错: {e}")
            return False
        if not entry:
            return False
        try:
            entry.click()
        except Exception as e:
            self._log_warning(f"点击返回房间入口失败: {e}")
            return False

        if _key != "item_left_back":
            return True

        # 个性主页左上角的返回点完只退掉主页这一层，还要再点一次标题栏返回才落回房间。
        titlebar_back = None
        if hasattr(finder, "wait_for_element_clickable"):
            titlebar_back = finder.wait_for_element_clickable(
                TITLEBAR_BACK_KEY, timeout=ROOM_RETURN_TIMEOUT
            )
        if not titlebar_back:
            return False
        try:
            titlebar_back.click()
            return True
        except Exception as e:
            self._log_warning(f"点击标题栏返回失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 送礼（#438）
    # ------------------------------------------------------------------

    async def open_gift_entry(self) -> bool:
        finder = self._finder()
        gesture = self._gesture()
        if finder is None or gesture is None:
            return False

        entry = finder.wait_for_element_clickable(GIFT_ENTRY_KEY, timeout=GIFT_POPUP_TIMEOUT)
        if not entry:
            self._log_warning("资料卡上没有送礼物入口")
            return False
        try:
            gesture.click_element_at(entry)
        except Exception as e:
            self._log_warning(f"点击送礼物入口失败: {e}")
            return False
        return True

    async def gift_popup_action(self) -> Optional[str]:
        """等「赠送」或「使用」出现，报出是哪一个；两个都没有就是弹窗没起来。"""
        finder = self._finder()
        if finder is None or not hasattr(finder, "wait_for_any_element"):
            return None
        try:
            key, _element = finder.wait_for_any_element(
                list(GIFT_ACTION_KEYS), timeout=GIFT_POPUP_TIMEOUT
            )
        except Exception as e:
            self._log_warning(f"等送礼弹窗出错: {e}")
            return None
        if key not in (GIFT_ACTION_GIVE, GIFT_ACTION_USE):
            return None
        return key

    async def read_gift_item_name(self) -> Optional[str]:
        finder = self._finder()
        if finder is None:
            return None
        try:
            item = finder.try_find_element(GIFT_ITEM_NAME_KEY, log=False)
        except Exception as e:
            self._log_warning(f"读选中礼物名字出错: {e}")
            return None
        if not item:
            return None
        raw = item.text or ""
        # 「名字x件数」是 App 的文案格式，件数不该出现在「XX 送你啦」里，因此在这里
        # 就拆掉；拆不掉就整段原样返回，与旧实现的 split 逻辑逐字等价。
        parts = raw.split("x")
        return parts[0] if len(parts) > 1 else raw

    async def read_gift_soul_power(self) -> Optional[str]:
        finder = self._finder()
        if finder is None:
            return None
        try:
            power = finder.try_find_element(GIFT_SOUL_POWER_KEY, log=False)
        except Exception:
            # 灵魂力只是日志里的一行读数，读不到不该让一次送礼失败。
            return None
        return power.text if power else None

    async def click_gift_item(self) -> bool:
        """点选中的礼物本身。

        沿用旧实现对 `luck_item` 的读法：`try_find_element`（弹窗里的静态文本，等它等于
        白等默认超时），点击走坐标手势。
        """
        finder = self._finder()
        gesture = self._gesture()
        if finder is None or gesture is None:
            return False
        try:
            item = finder.try_find_element(GIFT_ITEM_NAME_KEY, log=False)
        except Exception as e:
            self._log_warning(f"找选中礼物 {GIFT_ITEM_NAME_KEY} 出错: {e}")
            return False
        if not item:
            return False
        try:
            return bool(gesture.click_element_at(item))
        except Exception as e:
            self._log_warning(f"点击选中礼物失败: {e}")
            return False

    async def click_gift_action(self) -> bool:
        """点弹窗上此刻存在的那个动作按钮。

        两个按钮互斥，所以先找到一个就点它；找不到也不记「找不到赠送控件」这种假警告 ——
        走背包道具路径时 `give_gift` 本来就不渲染。
        """
        finder = self._finder()
        gesture = self._gesture()
        if finder is None or gesture is None:
            return False
        for key in GIFT_ACTION_KEYS:
            try:
                control = finder.try_find_element(key, log=False)
            except Exception:
                continue
            if not control:
                continue
            try:
                return bool(gesture.click_element_at(control))
            except Exception as e:
                self._log_warning(f"点击 {key} 失败: {e}")
                return False
        return False

    async def confirm_gift_use(self) -> bool:
        """等确认框出来并点掉。

        沿用旧实现的两步原样：`wait_for_element('confirm_use')` 等它弹出来，再对它自己
        `.click()`（不是坐标点击 —— 确认框是系统弹出的对话框，按钮位置已经由系统定死）。
        """
        finder = self._finder()
        if finder is None:
            return False
        try:
            confirm = finder.wait_for_element(GIFT_CONFIRM_KEY, timeout=GIFT_POPUP_TIMEOUT)
        except Exception as e:
            self._log_warning(f"等确认使用按钮出错: {e}")
            return False
        if not confirm:
            return False
        try:
            confirm.click()
        except Exception as e:
            self._log_warning(f"点击确认使用按钮失败: {e}")
            return False
        return True

    async def dismiss_gift_popup(self) -> bool:
        finder = self._finder()
        gesture = self._gesture()
        if finder is None or gesture is None:
            return False
        marker = self._gift_popup_marker()
        if marker is None:
            # 幂等：弹窗本来就没开着，这一步已经完成了。
            return True

        for key in GIFT_POPUP_CLOSE_KEYS:
            try:
                close_btn = None
                if hasattr(finder, "wait_for_element_clickable"):
                    close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn and hasattr(finder, "try_find_element"):
                    close_btn = finder.try_find_element(key, log=False)
                if not close_btn:
                    continue
                if not gesture.click_element_at(close_btn):
                    self._log_warning(f"点击送礼弹窗关闭按钮 {key} 失败")
                    continue
                # 关掉了不能就算数：按弹窗自己的动作按钮确认它真的走了，否则调用方会把
                # 一张还悬着的弹窗当成已经收拾干净。
                if hasattr(finder, "wait_for_element_disappear"):
                    finder.wait_for_element_disappear(
                        marker, timeout=GIFT_POPUP_TIMEOUT, poll_frequency=0.1
                    )
                if self._gift_popup_marker() is None:
                    return True
            except Exception as e:
                self._log_warning(f"收送礼弹窗时 {key} 出错: {e}")
        return False

    def _gift_popup_marker(self) -> Optional[str]:
        """弹窗此刻盖着的话报出它的标记 key（赠送或使用），没盖着返回 None。

        弹窗没有自己的容器控件，能证明「它还在」的就是那两个互斥的动作按钮 —— 与旧实现
        用 `wait_for_any_element(['give_gift', 'use_item'])` 判断弹窗到没到位同源。
        """
        finder = self._finder()
        if finder is None:
            return None
        for key in GIFT_ACTION_KEYS:
            try:
                if finder.try_find_element(key, log=False):
                    return key
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # 房管（#439）
    # ------------------------------------------------------------------

    async def read_admin_invite_label(self) -> Optional[str]:
        """读房管开关的文案；按钮没渲染出来返回 None。

        等待沿用旧 `AdminManager` 的那一次 `wait_for_element_clickable('manager_invite')`：
        读不到正是「没有这枚按钮」那条失败路径，等一下是值得的。
        """
        finder = self._finder()
        if finder is None:
            return None
        try:
            invite = finder.wait_for_element_clickable(
                ADMIN_INVITE_KEY, timeout=ADMIN_CONTROL_TIMEOUT
            )
        except Exception as e:
            self._log_warning(f"等房管开关出错: {e}")
            return None
        if not invite:
            return None
        try:
            return invite.text
        except Exception as e:
            self._log_warning(f"读房管开关文案出错: {e}")
            return None

    async def click_admin_invite(self) -> bool:
        """点房管开关。

        刻意**不再等一次**：文案刚才是靠等出来的，按钮此刻就在页面上，再等一遍只是在白
        费 `wait_for_element_clickable` 的默认超时。
        """
        finder = self._finder()
        if finder is None:
            return False
        try:
            invite = finder.try_find_element(ADMIN_INVITE_KEY, log=False)
        except Exception as e:
            self._log_warning(f"找房管开关出错: {e}")
            return False
        if not invite:
            return False
        try:
            invite.click()
            return True
        except Exception as e:
            self._log_warning(f"点击房管开关失败: {e}")
            return False

    async def confirm_admin_action(self, action: str) -> bool:
        """等确认框弹出，点掉它里面对应动作的按钮。

        沿用旧实现的两步原样：`wait_for_element_clickable(key)` 等它弹出来，再对它自己
        `.click()`（不是坐标点击 —— 确认框是系统弹出的对话框，按钮位置由系统定死）。
        """
        key = ADMIN_CONFIRM_KEYS.get(action)
        if key is None:
            return False
        finder = self._finder()
        if finder is None:
            return False
        try:
            confirm = finder.wait_for_element_clickable(key, timeout=ADMIN_CONTROL_TIMEOUT)
        except Exception as e:
            self._log_warning(f"等房管确认框出错: {e}")
            return False
        if not confirm:
            return False
        try:
            confirm.click()
            return True
        except Exception as e:
            self._log_warning(f"点击房管确认框 {key} 失败: {e}")
            return False

    async def dismiss_admin_confirm(self) -> bool:
        """确认框没被点掉时，按顺序试页内 X 收掉它。"""
        finder = self._finder()
        gesture = self._gesture()
        if finder is None or gesture is None:
            return False
        marker = self._admin_confirm_marker()
        if marker is None:
            # 幂等：确认框本来就没开着，这一步已经完成了。
            return True

        for key in ADMIN_CONFIRM_CLOSE_KEYS:
            try:
                close_btn = None
                if hasattr(finder, "wait_for_element_clickable"):
                    close_btn = finder.wait_for_element_clickable(key, timeout=1.5)
                if not close_btn and hasattr(finder, "try_find_element"):
                    close_btn = finder.try_find_element(key, log=False)
                if not close_btn:
                    continue
                if not gesture.click_element_at(close_btn):
                    self._log_warning(f"点击房管确认框关闭按钮 {key} 失败")
                    continue
                # 关掉了不能就算数：按确认框自己的按钮确认它真的走了，否则调用方会把
                # 一个还悬着的弹窗当成已经收拾干净。
                if hasattr(finder, "wait_for_element_disappear"):
                    finder.wait_for_element_disappear(
                        marker, timeout=ADMIN_CONTROL_TIMEOUT, poll_frequency=0.1
                    )
                if self._admin_confirm_marker() is None:
                    return True
            except Exception as e:
                self._log_warning(f"收房管确认框时 {key} 出错: {e}")
        return False

    def _admin_confirm_marker(self) -> Optional[str]:
        """房管确认框此刻盖着的话报出它的按钮 key，没盖着返回 None。

        与 `_gift_popup_marker` 同理：确认框没有自己的容器控件，能证明「它还在」的就是
        那两个互斥的动作按钮 —— 它们也是旧实现分别等的那两个 key。
        """
        finder = self._finder()
        if finder is None:
            return None
        for key in ADMIN_CONFIRM_KEYS.values():
            try:
                if finder.try_find_element(key, log=False):
                    return key
            except Exception:
                continue
        return None

    def _gesture(self):
        """手势处理器缺席就退化成「这一步做不了」，而不是抛 AttributeError。"""
        handler = self._handler
        if handler is None:
            return None
        gesture = getattr(handler, "gesture_handler", None)
        if gesture is None or not hasattr(gesture, "click_element_at"):
            return None
        return gesture

    def _find_row_element(self, finder, visible_username: str):
        """在当前已渲染的行里找昵称匹配的那一行，返回**行元素**本身。

        与 `find_member_row` 分开是因为两者要的不是一个东西：那里要的是读数（值），
        这里要的是「可点的那一行」。行元素只在这个方法里活一次 —— 出去了就交给 click()。
        """
        container = finder.try_find_element(ONLINE_CONTAINER_KEY, log=False)
        if not container:
            return None
        for row in finder.find_child_elements(container, ROW_CONTAINER_KEY):
            try:
                name_elem = finder.find_child_element(row, ROW_NAME_KEY)
                if not name_elem:
                    continue
                # 只按 UI 上显示的昵称匹配：canonical 名在这里永远不相等。
                if (name_elem.text or "") == visible_username:
                    return row
            except Exception:
                # 滑动途中行会失效是常态，读坏就跳过这一行。
                continue
        return None

    def _wait_for_profile_card(self, finder) -> bool:
        """等资料卡出现（按它自己的昵称元素判据）。"""
        try:
            card = finder.wait_for_element(
                PROFILE_CARD_NICKNAME_KEY, timeout=PROFILE_CARD_TIMEOUT
            )
            return bool(card)
        except Exception:
            return False

    def _finder(self):
        """handler / element_finder 任一缺席都退化成「App 不可用」。"""
        handler = self._handler
        if handler is None:
            return None
        return getattr(handler, "element_finder", None)
    def _swipe_geometry(self, container):
        """容器内滑动的起止坐标：手指从 0.75 高度划到 0.30 高度。

        算不出来时返回三个 None，由调用方回落到固定坐标 —— 与旧实现相同的处理，
        免得一次坐标读不到就彻底不能滚。
        """
        try:
            loc = container.location
            size = container.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            return (
                left + int(width * 0.5),
                top + int(height * 0.75),
                top + int(height * 0.30),
            )
        except Exception:
            return None, None, None

    def _log_warning(self, message: str) -> None:
        handler = self._handler
        logger = getattr(handler, "logger", None) if handler is not None else None
        if logger is not None:
            logger.warning(f"[online_drawer] {message}")
