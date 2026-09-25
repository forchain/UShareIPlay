"""聊天窗口的观察与补漏（MessageManager）。

对接缝的两点说明：

1. **窗口状态不再对外暴露**。原先 `recent_chats` / `latest_chats` 是两个公有
   deque，`MessageContentEvent` 一边往里塞、一边复制 `maxlen=3` 的语义来做
   diff —— 事件因此在解释 manager 的实现细节，而且测试只能把算法抄一份来验证。
   现在 diff 算法、maxlen 与锚点回落都在 `observe()` 里，对外只给一个
   `ChatDelta`。
2. **实时与补漏共用一套派发**。两条路径原先各写一份发言者分类与礼物处理；
   现在 `dispatch()` 是唯一实现，回溯路径用 `from_backfill` 说明它发现的行
   来自回滚（命令入队而不是立即执行、入场横幅不当作刚返回）。
"""

from collections import deque
from dataclasses import dataclass
import traceback

from ushareiplay.core.chat_intake import (
    QUEUE_COMMAND_PREFIX_CHARS,
    ChatIntakeKind,
    classify_chat_line,
    strip_quoted_segment,
)
from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton
from ushareiplay.models.message_info import MessageInfo


# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger.

    Delegates to the RuntimeLogging module so the chat log inherits the
    same path / archive / handler / reset invariants as the app log.
    """
    global chat_logger
    if chat_logger is None:
        from ushareiplay.core.runtime_logging import get_runtime_logging

        chat_logger = get_runtime_logging().attach_chat_logger(config)
    return chat_logger


@dataclass(frozen=True)
class ChatDelta:
    """一次聊天窗口观察的结果。

    Attributes:
        new_lines: 相对上一次观察新增的聊天行，保持屏幕上的先后顺序。
        anchor: 上一次观察的最后一行（本次的滚动锚点）；窗口此前为空时为 None。
        missed: 锚点已不在屏幕上 —— 两次观察之间有滚过去、没被看到的行。
    """

    new_lines: tuple[str, ...] = ()
    anchor: str | None = None
    missed: bool = False


class MessageManager(Singleton):
    #: 上一次观察保留多少行用于去重（比屏幕可见行数窄，因此存在 missed 兜底）
    RECENT_MAXLEN = 3

    def __init__(self):
        """Initialize MessageManager with handler, previous messages, recent messages"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._chat_logger = None

        self.previous_messages = {}
        self._recent = deque(maxlen=self.RECENT_MAXLEN)

    @property
    def handler(self):
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler

            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def chat_logger(self):
        if self._chat_logger is None:
            self._chat_logger = get_chat_logger(self.handler.config)
        return self._chat_logger

    def _get_seat_manager(self):
        from ushareiplay.managers.seat_manager import SeatManager

        return SeatManager.get_instance()

    async def resolve_room_owner(self) -> str | None:
        """房间房主名：配置优先（走 ADR-0008 的 RolePolicy），否则回落到库里的房主。

        配置读取原先在两个地方各写一份（本模块与 MessageContentEvent，后者还有
        第三个回落），现在只有这一个入口。
        """
        from ushareiplay.core.roles import RolePolicy

        config = getattr(self.handler, "config", None)
        owner = RolePolicy(config if isinstance(config, dict) else None).room_owner
        if owner:
            return owner

        try:
            from ushareiplay.models import User
            owner_user = await User.filter(level=9).first()
            if owner_user:
                return owner_user.username
        except Exception:
            self.handler.logger.error(f"解析房主失败: {traceback.format_exc()}")
        return None

    # ------------------------------------------------------------------
    # 观察：窗口状态与 diff 只在这里
    # ------------------------------------------------------------------

    def observe(self, content_list) -> ChatDelta:
        """观察一次聊天窗口，返回相对上次观察的增量，并提交新的窗口状态。

        diff 算法原先住在 `MessageContentEvent.handle` 里，直接操作两个公有
        deque；它和 `maxlen` 的相互作用（前向对齐、窗口比 maxlen 宽时的兜底）
        因此只存在于事件里。现在它和 `_recent` 一起留在本模块。
        """
        contents = [c for c in (content_list or []) if c]
        previous = self._recent
        anchor = previous[-1] if previous else None

        if not previous:
            new_lines = tuple(contents)
            missed = False
        else:
            new_lines, missed = self._diff_against_window(contents, previous)
            if missed and anchor is not None:
                new_lines, missed = self._apply_anchor_fallback(contents, anchor, new_lines)

        self._recent = deque(new_lines, maxlen=self.RECENT_MAXLEN)
        return ChatDelta(new_lines=new_lines, anchor=anchor, missed=missed)

    @staticmethod
    def _diff_against_window(contents, previous) -> tuple[tuple[str, ...], bool]:
        """前向对齐：找到最小的偏移，使上次窗口的后缀对上本次列表的前缀。

        对齐点之后的行就是新增行。全部偏移都失配时说明中间漏了行（missed）。
        """
        recent_len = len(previous)
        content_len = len(contents)
        new_lines: list[str] = []

        for i in range(recent_len):
            matched_to_end = False
            for j in range(content_len):
                ii = i + j
                if ii < recent_len:
                    if contents[j] != previous[ii]:
                        break
                    if ii == recent_len - 1 and j == content_len - 1:
                        matched_to_end = True
                        break
                else:
                    new_lines.append(contents[j])
            if matched_to_end:
                break
            if new_lines:
                break
            if i == recent_len - 1:
                # 一次都没对上：窗口整段滚走了，本次列表全部当作新增
                return tuple(contents), True

        return tuple(new_lines), False

    @staticmethod
    def _apply_anchor_fallback(contents, anchor, new_lines) -> tuple[tuple[str, ...], bool]:
        """锚点仍在屏幕上时，`missed` 是假的 —— 只是窗口比 maxlen 宽。

        `contents` 比 `RECENT_MAXLEN` 长时前向对齐会在 j=0 整体失配；此时若锚点
        确实可见，就只保留锚点之后的行。
        """
        for idx, content in enumerate(contents):
            if content == anchor:
                return tuple(contents[idx + 1:]), False
        return new_lines, True

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    # ------------------------------------------------------------------
    # 派发：实时与补漏共用同一套分类与处理
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        lines,
        *,
        room_owner: str | None = None,
        from_backfill: bool = False,
    ) -> list[MessageInfo]:
        """把聊天行按类型派发到各自的处理器。

        实时扫描与回滚补漏原先各写一份分类与处理（礼物处理两份、mention 两份），
        现在只有这一个实现。两条路径真正的差别只有一处，由 `from_backfill`
        说明：回滚发现的行属于历史，命令入队等 runtime 管线执行、入场横幅不当作
        「用户刚返回」；其余处理完全一致。

        Args:
            lines: 要派发的聊天行，通常来自 `observe()` 的 `new_lines`
            room_owner: 房主名，用于识别「送给房主」的礼物
            from_backfill: 这些行来自回滚补漏

        Returns:
            本批出现的命令消息。实时路径不代为入队（执行由
            `CommandManager.execute_chat_scan` 完成），仅用其判断是否要执行命令；
            补漏路径在此入队。
        """
        chat_logger = self.chat_logger
        commands: list[MessageInfo] = []

        for content in lines:
            result = classify_chat_line(content, room_owner=room_owner)
            kind = result.kind

            if kind == ChatIntakeKind.USER_RETURN:
                if from_backfill:
                    # 回溯到的入场横幅是历史，不触发「用户返回」事件
                    chat_logger.info(content)
                    continue
                await self._handle_user_return(result, content)
                continue

            if kind == ChatIntakeKind.GIFT_RECEIVE:
                chat_logger.critical(content)
                heat_value = getattr(result, "heat_value", 0)
                if heat_value > 0:
                    self.handler.logger.info(
                        f"Heat contribution received from user '{result.nickname}': +{heat_value} heat"
                    )
                else:
                    self.handler.logger.info(
                        f"Gift received from user '{result.nickname}' (sent to room_owner '{room_owner}')"
                    )
                await self.handle_gift_receive(result)
                continue

            if kind == ChatIntakeKind.KEYWORD_MENTION:
                from ushareiplay.managers.keyword_manager import KeywordManager
                await KeywordManager.instance().dispatch_mention(result, sleep_exempt=True)
                chat_logger.critical(content)
                continue

            if kind == ChatIntakeKind.COMMAND:
                if not result.text.strip(QUEUE_COMMAND_PREFIX_CHARS).strip():
                    # 只有触发符、没有内容：当成普通发言记日志
                    chat_logger.info(content)
                    continue
                chat_logger.critical(content)
                message = MessageInfo(result.text, result.nickname)
                if from_backfill:
                    await MessageQueue.instance().put_message(message)
                    self.handler.logger.info(f"Missed command added to queue: {result.text}")
                commands.append(message)
                continue

            chat_logger.info(content)

        return commands

    async def _handle_user_return(self, result, content: str) -> None:
        """入场通知：由 PresenceTracker 判定是否算作「用户返回」。"""
        from ushareiplay.state.presence_tracker import PresenceTracker

        presence_tracker = PresenceTracker.instance()
        if presence_tracker.should_trigger_return(result.nickname):
            presence_tracker.record_return(result.nickname)
            self.handler.logger.critical(f"User returned: {result.nickname}")
            self.chat_logger.critical(content)
            from ushareiplay.managers.command_manager import CommandManager
            await CommandManager.instance().notify_user_return(result.nickname)
        else:
            self.handler.logger.info(
                f"User entrance message for '{result.nickname}' skipped return event (not online or recently entered/returned)"
            )
            self.chat_logger.info(content)

    async def handle_gift_receive(self, result) -> None:
        """收礼物与热力值贡献：升级等级、发感谢消息、触发自定义命令。

        实时路径与补漏路径原先各有一份实现，只有日志文案不同。
        """
        try:
            from ushareiplay.dal.user_dao import UserDAO

            username = result.nickname
            heat_value = getattr(result, "heat_value", 0)
            if heat_value > 0:
                user = await UserDAO.record_heat_contribution(username, heat_value)
            else:
                user = await UserDAO.record_owner_gift(username)

            if user:
                self.handler.logger.info(
                    f"User '{user.username}' status after gift/heat processing: "
                    f"level=L{user.level}, cumulative_heat={user.heat_value}"
                )

            thank_msg = MessageInfo(content=f"@{username} 谢谢", nickname=username)
            await MessageQueue.instance().put_message(thank_msg)
            self.handler.logger.info(f"Enqueued thank-you message '@{username} 谢谢' to MessageQueue")

            from ushareiplay.managers.command_manager import CommandManager
            await CommandManager.instance().notify_gift_receive(username)
        except Exception:
            self.handler.logger.error(f"Error handling gift receive: {traceback.format_exc()}")

    async def process_missed_messages(self, anchor: str | None = None) -> set[str]:
        """回溯补漏：从 anchor 往回滚动，处理实时扫描没看到的行。

        Args:
            anchor: 上一次已处理的行（由 `observe()` 的 ChatDelta 给出）。
                省略时取窗口里最后一行，便于单独调用。

        Returns:
            本次发现的命令文本集合；没有可回溯内容时返回 None。
        """
        if not self.handler.key_actions.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        # 回溯补漏前，确保座位面板收起（避免聊天区域过小导致回溯变慢）
        try:
            seat_manager = self._get_seat_manager()
            if seat_manager:
                await seat_manager.prepare_for_chat_scan()
        except Exception:
            self.handler.logger.error(f"收起座位失败（不影响补漏继续执行）: {traceback.format_exc()}")

        if anchor is None:
            anchor = self._recent[-1] if self._recent else None
        if not anchor:
            return None

        # Quoted Messages are composed onto the scanned line but never rendered
        # in the sender's own bubble, so scroll/skip on the quote-free line.
        scroll_anchor = strip_quoted_segment(anchor) or anchor

        self.handler.logger.critical(f"last_chat={anchor}")

        key, element, attribute_values = self.handler.gesture_handler.scroll_container_until_element(
            'message_content',
            'message_list',
            'down',
            'content-desc|text',
            scroll_anchor,
        )

        # send empty message to scroll to bottom instantly (always, even if
        # the anchor was not found — otherwise the view stays on old messages)
        self.handler.send_message("")

        if not key:
            return None

        # Scanned lines carry no quote; compare on the quote-free form of what we
        # already processed so a reply is not re-reported (and re-dispatched).
        known_chats = {strip_quoted_segment(chat) for chat in self._recent}
        missed_lines: list[str] = []
        for chat in attribute_values:
            if scroll_anchor == strip_quoted_segment(chat):
                continue
            if chat in known_chats or chat in missed_lines:
                continue
            self.chat_logger.warning(chat)
            missed_lines.append(chat)

        commands = await self.dispatch(
            missed_lines,
            room_owner=await self.resolve_room_owner(),
            from_backfill=True,
        )
        return {message.content for message in commands}

    async def process_new_messages(self, lines=None):
        """把新出现的聊天行里的命令交给 CommandManager 立即执行。

        Args:
            lines: 要扫描的行；省略时取窗口里最近的行（单独调用时的便利路径）。
        """
        if not self.handler.key_actions.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            return None

        from ushareiplay.managers.command_manager import CommandManager
        return await CommandManager.instance().execute_chat_scan(
            self._recent if lines is None else lines
        )
