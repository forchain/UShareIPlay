"""
消息获取与补漏（MessageManager）

你当前实现的核心意图（我按代码结构理解）：
- 每轮从 `message_list` 容器读取可见消息容器（ViewGroup）。
- 用 `recent_messages` 作为“最近看到过的原始 chat_text”缓存（当前 maxlen=3）。
- 以当前屏第一条 `first_text` 与 `recent_messages` 对比，判断是否发生“漏看/错过”：
  - 未漏看：直接处理当前屏容器，找出新的 element_id 消息用于命令执行。
  - 漏看：先向下回翻，直到屏内出现“上一条 last_message”（锚点），再从锚点之后补处理一屏；
         接着向上翻若干次，直到回到最新（通过 first_text 命中判定）。

本文件新增内容（不改变你原有策略，只增强可观测性）：
- 关键分支加 logger（info/debug/warning/error）。
- 额外写入 NDJSON 到 `.cursor/debug.log`，便于你之后按 runId 回放每轮发生了什么。
"""

import logging
import re
import traceback
from collections import deque
from dataclasses import dataclass

from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import StaleElementReferenceException

from ..core.singleton import Singleton
from ..core.log_formatter import ColoredFormatter

# region agent log
# Debug mode: 将关键状态写到 NDJSON（便于你离线对齐每次循环的分支与数据）
import json
import os
import time

_DEBUG_LOG_PATH = "/home/tony/github.com/forchain/UShareIPlay/.cursor/debug.log"


def _dbg(hypothesis_id: str, location: str, message: str, data=None, run_id: str = "review-1"):
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG_PATH), exist_ok=True)
        payload = {
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # debug 日志失败不影响主逻辑
        pass


# endregion

# Global chat logger - will be initialized when needed
chat_logger = None


def get_chat_logger(config=None):
    """Get or create chat logger with configurable directory"""
    global chat_logger
    import yaml
    if chat_logger is None:
        # 直接加载全局 config.yaml
        try:
            with open('config.yaml', 'r', encoding='utf-8') as f:
                global_config = yaml.safe_load(f)
            log_dir = global_config.get('logging', {}).get('directory', 'logs')
        except Exception as e:
            print(f"[日志调试] 加载 config.yaml 失败: {e}")
            log_dir = 'logs'
        print(f"[日志调试] chat.log 日志目录: {log_dir}, 绝对路径: {os.path.abspath(log_dir)}")
        # Create logs directory if it doesn't exist (supports relative paths)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        # Create chat logger
        chat_logger = logging.getLogger('chat')
        chat_logger.setLevel(logging.INFO)
        # Clear any existing handlers
        if chat_logger.hasHandlers():
            chat_logger.handlers.clear()
        log_file = f'{log_dir}/chat.log'
        handler = logging.FileHandler(log_file, encoding='utf-8')
        # Use ColoredFormatter without colors for file logging
        formatter = ColoredFormatter(
            fmt='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%m-%d %H:%M:%S',
            use_colors=False
        )
        handler.setFormatter(formatter)
        chat_logger.addHandler(handler)
    return chat_logger


@dataclass
class MessageInfo:
    """Data class for message information"""
    content: str
    nickname: str
    avatar_element: object  # WebElement for avatar, always exists
    relation_tag: bool = False  # True if user has relation tag


class MessageManager(Singleton):
    def __init__(self):
        """Initialize MessageManager with handler, previous messages, recent messages"""
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._greeting_manager = None
        self._chat_logger = None

        self.previous_messages = {}
        self.recent_chats = deque(maxlen=3)  # Keep track of recent messages to avoid duplicates

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def greeting_manager(self):
        """延迟获取 GreetingManager 实例"""
        if self._greeting_manager is None:
            from .greeting_manager import GreetingManager
            self._greeting_manager = GreetingManager.instance()
        return self._greeting_manager

    @property
    def chat_logger(self):
        """延迟获取 chat_logger 实例"""
        if self._chat_logger is None:
            self._chat_logger = get_chat_logger(self.handler.config)
        return self._chat_logger

    def _get_seat_manager(self):
        """Get the seat_manager lazily to avoid circular import issues"""
        from .seat_manager import seat_manager
        return seat_manager

    def get_party_id(self):
        party_id = self.handler.party_id
        if not party_id:
            party_id = self.handler.config['default_party_id']
        return party_id

    async def get_messages_from_containers(self, containers):
        """
        将 UI containers 转成 current_messages/new_messages（用于命令执行）。

        说明：
        - `current_messages` 以 container.id 为 key，值为 MessageInfo（或 greeting_info）。
        - 通过 `previous_messages` 做差集，得到本轮“新增容器”的消息。

        风险点（仅注释，不在此处改行为）：
        - 你这里把 greeting_info 放进 `recent_messages` 的方式用了 walrus 组合表达式，
          很容易把 bool 存进 deque（见下方日志会记录）。
        """
        # Process each container and collect message info
        current_messages = {}  # Dict to store element_id: MessageInfo pairs

        for container in containers:
            message_info = await self.process_container_message(container)
            greeting_info = await self.greeting_manager.process_container_greeting(container)

            if message_info:
                current_messages[container.id] = message_info
            if greeting_info:
                current_messages[container.id] = greeting_info
                # NOTE: 这里的写法 `content := greeting_info.content and ...` 在 Python 里会先计算 and，
                # 最终 content 可能是 bool，而不是文本；这会污染 recent_messages。
                # 先加日志观测，后续再用证据决定是否要改为：
                #   content = greeting_info.content
                #   if content and content not in self.recent_messages: ...
                try:
                    content = getattr(greeting_info, "content", None)
                    if content and content not in self.recent_chats:
                        self.recent_chats.append(content)
                        self.handler.logger.debug(
                            f"[greeting] appended to recent_messages: {content!r}"
                        )
                        _dbg("Hc", "message_manager.py:get_messages_from_containers",
                             "append_recent_from_greeting",
                             {"value": repr(content), "type": str(type(content))})
                except Exception:
                    self.handler.logger.warning(
                        f"[greeting] failed to append recent: {traceback.format_exc()}"
                    )
                    _dbg("Hc", "message_manager.py:get_messages_from_containers",
                         "append_recent_from_greeting_failed",
                         {"trace": traceback.format_exc()})

        # Update previous message IDs and return new messages
        new_messages = {}  # Changed from list to dict
        for element_id, message_info in current_messages.items():
            if element_id not in self.previous_messages:
                new_messages[element_id] = message_info  # Store as dict

        self.previous_messages = current_messages
        return new_messages if new_messages else None

    async def get_latest_messages(self):
        """Get new message contents that weren't seen before
        Returns:
            dict: New messages if any found
            None: No new messages (normal state)
            'ABNORMAL_STATE': Unable to access message list (abnormal state)
        """
        if not self.handler.switch_to_app():
            self.handler.logger.error("Failed to switch to Soul app")
            _dbg("H1", "message_manager.py:get_latest_messages", "switch_to_app_failed")
            return 'ABNORMAL_STATE'

        # Get message list container
        message_list = self.handler.try_find_element_plus('message_list', log=False)
        if not message_list:
            # self.handler.press_back()
            self.handler.logger.error("Failed to find message list")
            _dbg("H1", "message_manager.py:get_latest_messages", "message_list_not_found", {
                "screen": "unknown",
            })
            return 'ABNORMAL_STATE'

        # Collapse seats if expanded and update focus count
        seat_manager = self._get_seat_manager()

        # 更新焦点计数
        if seat_manager and hasattr(seat_manager, 'focus'):
            # self.handler.logger.info("更新焦点计数...")
            seat_manager.focus.update()

        # Get all ViewGroup containers
        try:
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
        except Exception as e:
            self.handler.logger.error('cannot find message_list element, might be in loading')
            _dbg("H1", "message_manager.py:get_latest_messages", "find_elements_failed", {
                "error": str(e),
            })
            return 'ABNORMAL_STATE'

        if len(containers) == 0:
            self.handler.logger.error("No message containers found")
            _dbg("H1", "message_manager.py:get_latest_messages", "no_containers")
            return 'ABNORMAL_STATE'

        first_chat = self.get_chat_text(containers[0])
        latest_chat = self.get_chat_text(containers[len(containers) - 1])
        is_chat_missed = first_chat not in self.recent_chats if first_chat else False

        self.handler.logger.debug(
            f"[messages] containers={len(containers)} first_chat={first_chat!r} latest_chat={latest_chat!r} missed={is_chat_missed} recent={list(self.recent_chats)!r}"
        )
        _dbg("H4", "message_manager.py:get_latest_messages", "screen_snapshot", {
            "container_count": len(containers),
            "first_chat": first_chat,
            "missed": is_chat_missed,
            "recent": [repr(x) for x in list(self.recent_chats)],
        })

        new_messages = {}
        # NOTE: 这里你希望取 recent_messages 的最后一条作为锚点（last_chat）。
        # 当前写法在 Python 中会报错（deque - int 不合法），先加 try/except 让日志把问题打出来。
        try:
            last_chat = self.recent_chats[-1] if len(self.recent_chats) > 0 else None
        except Exception:
            last_chat = None
            self.handler.logger.error(f"[messages] compute last_chat failed: {traceback.format_exc()}")
            _dbg("Hc", "message_manager.py:get_latest_messages", "last_message_compute_failed", {
                "trace": traceback.format_exc(),
                "recent": [repr(x) for x in list(self.recent_chats)],
            })
        if not is_chat_missed:
            # NOTE: get_messages_from_containers 是 async，这里需要 await 才会真正执行。
            # 先加日志观测返回类型；后续根据运行时证据再决定是否统一修正。
            try:
                new_messages = await self.get_messages_from_containers(containers)
                _dbg("H4", "message_manager.py:get_latest_messages", "no_miss_processed", {
                    "new_count": len(new_messages) if isinstance(new_messages, dict) else None,
                    "type": str(type(new_messages)),
                })
            except Exception:
                self.handler.logger.error(f"[messages] no_miss processing failed: {traceback.format_exc()}")
                _dbg("Hc", "message_manager.py:get_latest_messages", "no_miss_processing_failed", {
                    "trace": traceback.format_exc(),
                })
                return 'ABNORMAL_STATE'
        else:
            # scroll back to the missing element
            self.handler.logger.warning(
                f"[messages] missed detected. first_chat not in recent. last_chat(anchor)={last_chat!r}"
            )
            _dbg("H4", "message_manager.py:get_latest_messages", "miss_detected", {
                "first_chat": first_chat,
                "anchor": last_chat,
            })

            try:
                # AppHandler.scroll_container_until_element 会在容器内滑动直到出现某个 child element。
                # 你这里传入 attribute_name/content-desc + attribute_value=last_chat，用于“按原始串定位锚点”。
                self.handler.scroll_container_until_element(
                    'message_content',
                    'message_list',
                    'down',
                    'content-desc',
                    last_chat,
                )
            except Exception:
                self.handler.logger.error(
                    f"[messages] scroll_container_until_element crashed: {traceback.format_exc()}")
                _dbg("Hc", "message_manager.py:get_latest_messages", "scroll_to_anchor_failed", {
                    "trace": traceback.format_exc(),
                    "anchor": last_chat,
                })
                return 'ABNORMAL_STATE'
            containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
            self.previous_messages = {}
            messages = await self.get_messages_from_containers(containers)
            is_new_message = False
            # NOTE: messages 是 dict 时，直接 for message in messages 会遍历 key（element_id），不是 MessageInfo。
            # 这里先按你当前写法补日志观测 messages 的真实类型与迭代对象。
            _dbg("Hc", "message_manager.py:get_latest_messages", "backfill_first_screen_type", {
                "type": str(type(messages)),
                "keys_sample": list(messages.keys())[:3] if isinstance(messages, dict) else None,
            })
            for element_id, message in (messages.items() if isinstance(messages, dict) else []):
                if getattr(message, "content", None) and message.content not in self.recent_chats:
                    if is_new_message:
                        new_messages[element_id] = message
                        self.previous_messages[element_id] = message
                    if message.content == latest_chat:
                        is_new_message = True

            # 预计算容器可视坐标
            loc = message_list.location
            size = message_list.size
            left = int(loc["x"])
            top = int(loc["y"])
            width = int(size["width"])
            height = int(size["height"])

            sx = int(left + width / 2)
            sy = int(top + height * 0.9)
            ex = sx
            ey = int(top + height * 0.1)

            max_tries = 10
            is_scrolled_to_latest = False
            for i in range(max_tries):
                self.handler._perform_swipe(sx, sy, ex, ey)
                containers = message_list.find_elements(AppiumBy.CLASS_NAME, "android.view.ViewGroup")
                messages = await self.get_messages_from_containers(containers)
                for element_id, message in messages.items():
                    new_element_id = element_id
                    if element_id in new_messages:
                        new_element_id = f"{element_id}_{i}"
                        self.handler.logger.warning(
                            f"Duplicate message found: {message.content}, new element id:{new_element_id}")
                    new_messages[new_element_id] = message
                    if message.content == last_chat:
                        is_scrolled_to_latest = True
                if is_scrolled_to_latest:
                    break

        return new_messages if new_messages else None

    def is_user_enter_message(self, message: str) -> tuple[bool, str]:
        """Check if message is a user enter notification
        Args:
            message: str, message to check
        Returns:
            tuple[bool, str]: (is_enter_message, username)
        """
        pattern = r"^(.+)(?:进来陪你聊天啦|坐着.+来啦).*?$"
        match = re.match(pattern, message)
        if match:
            return True, match.group(1)
        return False, ""

    def get_chat_text(self, container):
        # Check if container has valid message content
        content_element = self.handler.find_child_element_plus(
            container,
            'message_content'
        )
        if not content_element:
            return None

        message_text = content_element.text
        content_desc = self.handler.try_get_attribute(content_element, 'content-desc')
        chat_text = content_desc if content_desc and content_desc != 'null' else message_text
        return chat_text

    async def process_container_message(self, container):
        """Process a single message container and return MessageInfo"""
        try:
            chat_text = self.get_chat_text(container)
            if not chat_text:
                return None

            # Check for duplicate message
            if chat_text not in self.recent_chats:
                is_enter, username = self.is_user_enter_message(chat_text)
                if is_enter:
                    self.handler.logger.critical(f"User entered: {username}")
                    # Notify all commands via CommandManager
                    from .command_manager import CommandManager
                    command_manager = CommandManager.instance()
                    command_modules = command_manager.get_command_modules()
                    for module in command_modules.values():
                        try:
                            if hasattr(module.command, 'user_enter'):
                                await module.command.user_enter(username)
                        except Exception:
                            self.handler.logger.error(f"Error in command user_enter: {traceback.format_exc()}")
                        continue
                self.chat_logger.info(chat_text)
                self.recent_chats.append(chat_text)

            # Parse message content using pattern
            pattern = r'souler\[.+\]说：:(.+)'
            match = re.match(pattern, chat_text)
            if not match:
                return None

            # Extract actual message content
            message_content = match.group(1).strip()

            # Get avatar element
            avatar_element = self.handler.find_child_element_plus(
                container,
                'sender_avatar'
            )
            if not avatar_element:
                return None

            # Get nickname
            nickname_element = self.handler.find_child_element_plus(
                container,
                'sender_nickname'
            )
            nickname = nickname_element.text if nickname_element else "Unknown"

            # Check for relation tag
            relation_tag = bool(self.handler.find_child_element_plus(
                container,
                'sender_relation'
            ))

            return MessageInfo(message_content, nickname, avatar_element, relation_tag)

        except StaleElementReferenceException:
            self.handler.logger.warning("Message element became stale")
            return None
        except Exception:
            self.handler.logger.error(f"Error processing message container: {traceback.format_exc()}")
            return None
