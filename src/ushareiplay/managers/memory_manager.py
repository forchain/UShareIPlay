import asyncio
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

from ushareiplay.core.singleton import Singleton

logger = logging.getLogger(__name__)


class MemoryManager(Singleton):
    """
    用户记忆系统管理器 (Memory Manager)
    - 管理用户聊天记录 (UserChatLog) 与长期记忆 (UserMemory)
    - 装配对话时的长期记忆 (铁律区 + 动态画像) 与短期临时记忆
    - 异步低优先级后台 Worker 执行记忆沉淀固化 (Memory Consolidation)
    """

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._consolidation_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._min_messages: int = 10
        self._min_level_for_long_term: int = 20
        self._worker_delay: float = 1.0
        self._enabled: bool = True
        self._last_user_trigger_time: Dict[str, float] = {}  # username -> timestamp for debouncing
        self._debounce_interval: float = 60.0  # 1 minute debounce for presence triggers

    def configure(self, config: Optional[Dict[str, Any]] = None):
        """配置记忆管理器参数"""
        cfg = config or {}
        llm_cfg = cfg.get("llm") or (cfg.get("soul", {}) or {}).get("llm", {})
        mem_cfg = (llm_cfg.get("memory") if isinstance(llm_cfg, dict) else {}) or {}
        
        self._enabled = bool(mem_cfg.get("enabled", True))
        self._min_messages = int(mem_cfg.get("min_messages", 10))
        self._min_level_for_long_term = int(mem_cfg.get("min_level_for_long_term", 20))
        self._worker_delay = float(mem_cfg.get("worker_delay_seconds", 1.0))
        self._config = cfg

    @property
    def min_messages(self) -> int:
        return self._min_messages

    @property
    def min_level_for_long_term(self) -> int:
        return self._min_level_for_long_term

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def record_user_chat(self, username: str, content: str):
        """记录用户 @群主 的发言"""
        if not self._enabled or not username or not content:
            return None
        from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
        return await UserChatLogDAO.create(username=username, content=content)

    async def get_user_dialogue_context(self, username: str, user_level: int = 0) -> dict:
        """获取用于对话注入的记忆上下文（长期铁律区、画像与短期临时聊天）。
        
        若用户等级低于 min_level_for_long_term（默认 20 级），仅加载短期临时聊天记录，不加载长期记忆。
        """
        if not self._enabled or not username:
            return {"directives": [], "profile": "", "short_term_chats": []}

        try:
            from ushareiplay.dal.user_dao import UserDAO
            from ushareiplay.dal.user_memory_dao import UserMemoryDAO
            from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO

            canonical_user = await UserDAO.get_or_create(username=username)
            memory = await UserMemoryDAO.get_by_user_id(canonical_user.id)

            if user_level >= self._min_level_for_long_term:
                directives = memory.immutable_directives if memory else []
                profile = memory.profile_summary if memory else ""
            else:
                directives = []
                profile = ""

            since = memory.last_consolidated_at if memory else None

            recent_logs = await UserChatLogDAO.get_unconsolidated_logs(
                user_id=canonical_user.id,
                since=since,
                limit=20,
            )
            return {
                "directives": directives or [],
                "profile": profile or "",
                "short_term_chats": [l.content for l in recent_logs],
                "last_consolidated_at": since,
            }
        except Exception:

            logger.error(f"Error fetching user dialogue context for {username}: {traceback.format_exc()}")
            return {"directives": [], "profile": "", "short_term_chats": []}

    async def start(self):
        """启动后台记忆沉淀 Worker"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("MemoryManager background worker started")

    async def stop(self):
        """停止后台记忆沉淀 Worker"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("MemoryManager background worker stopped")

    def schedule_consolidation_user(self, username: str, force: bool = False):
        """非阻塞调度单用户记忆沉淀检查（带防抖）"""
        if not self._enabled or not username:
            return

        now = asyncio.get_event_loop().time()
        if not force:
            last_time = self._last_user_trigger_time.get(username, 0)
            if now - last_time < self._debounce_interval:
                logger.debug(f"Memory consolidation for {username} skipped due to debouncing")
                return

        self._last_user_trigger_time[username] = now
        self._consolidation_queue.put_nowait({"type": "user", "username": username})
        logger.debug(f"Scheduled memory consolidation task for user {username}")

    def schedule_consolidation_all(self):
        """非阻塞调度全局扫描记忆沉淀检查"""
        if not self._enabled:
            return
        self._consolidation_queue.put_nowait({"type": "global"})
        logger.info("Scheduled global memory consolidation sweep")

    async def _worker_loop(self):
        """低优先级串行后台消费循环"""
        while self._running:
            try:
                task = await self._consolidation_queue.get()
                task_type = task.get("type")

                if task_type == "user":
                    username = task.get("username")
                    if username:
                        await self._consolidate_single_user(username)
                elif task_type == "global":
                    await self._consolidate_all_eligible_users()

                self._consolidation_queue.task_done()
                if self._worker_delay > 0:
                    await asyncio.sleep(self._worker_delay)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.error(f"Error in MemoryManager worker loop: {traceback.format_exc()}")
                await asyncio.sleep(2.0)

    async def _consolidate_single_user(self, username: str) -> bool:
        """检查并沉淀单个用户的短期记忆"""
        try:
            from ushareiplay.dal.user_dao import UserDAO
            from ushareiplay.dal.user_memory_dao import UserMemoryDAO
            from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO

            canonical_user = await UserDAO.get_or_create(username=username)
            memory = await UserMemoryDAO.get_by_user_id(canonical_user.id)
            since = memory.last_consolidated_at if memory else None

            unconsolidated_count = await UserChatLogDAO.count_unconsolidated(canonical_user.id, since=since)
            if unconsolidated_count < self._min_messages:
                logger.debug(
                    f"User {username} (id={canonical_user.id}) unconsolidated logs ({unconsolidated_count}) < min_messages ({self._min_messages}), skipping."
                )
                return False

            logs = await UserChatLogDAO.get_unconsolidated_logs(canonical_user.id, since=since)
            if not logs:
                return False

            cutoff_time = logs[-1].created_at
            existing_directives = memory.immutable_directives if memory else []
            existing_profile = memory.profile_summary if memory else ""
            log_texts = [l.content for l in logs]

            success, updated_directives, updated_profile = await self._call_consolidation_llm(
                user_name=canonical_user.username,
                existing_directives=existing_directives,
                existing_profile=existing_profile,
                new_messages=log_texts,
            )

            if success:
                await UserMemoryDAO.update_memory(
                    user_id=canonical_user.id,
                    directives=updated_directives,
                    profile_summary=updated_profile,
                    consolidated_at=cutoff_time,
                )
                logger.info(
                    f"Memory successfully consolidated for user '{canonical_user.username}' (id={canonical_user.id}) up to {cutoff_time} ({len(logs)} messages processed)"
                )
                return True
            else:
                logger.warning(
                    f"Memory consolidation failed for user '{canonical_user.username}', cursor not advanced."
                )
                return False

        except Exception:
            logger.error(f"Error consolidating memory for {username}: {traceback.format_exc()}")
            return False

    async def _consolidate_all_eligible_users(self):
        """全局扫描并沉淀所有达到阈值的活跃用户"""
        try:
            from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
            from ushareiplay.dal.user_dao import UserDAO

            eligible_users = await UserChatLogDAO.get_active_user_ids_with_unconsolidated_logs(
                min_count=self._min_messages
            )
            logger.info(f"Global memory sweep found {len(eligible_users)} eligible users with >= {self._min_messages} messages")

            for user_id, count in eligible_users:
                user = await UserDAO.get_by_id(user_id)
                if user:
                    await self._consolidate_single_user(user.username)
                    if self._worker_delay > 0:
                        await asyncio.sleep(self._worker_delay)

        except Exception:
            logger.error(f"Error in global memory consolidation sweep: {traceback.format_exc()}")

    async def _call_consolidation_llm(
        self,
        user_name: str,
        existing_directives: List[str],
        existing_profile: str,
        new_messages: List[str],
    ) -> tuple[bool, List[str], str]:
        """调用 LLM 提炼长期记忆（更新铁律与画像）"""
        try:
            from ushareiplay.managers.keyword_manager import KeywordManager
            km = KeywordManager.instance() if KeywordManager.is_initialized() else None
            resolver = getattr(km, "nl_resolver", None)
            if not resolver or not resolver.enabled or not resolver.api_key:
                logger.debug("LLM not enabled/configured for memory consolidation")
                return False, existing_directives, existing_profile

            directives_str = "\n".join([f"- {d}" for d in existing_directives]) if existing_directives else "无"
            profile_str = existing_profile if existing_profile else "无"
            messages_str = "\n".join([f"{i+1}. {m}" for i, m in enumerate(new_messages)])

            prompt = f"""你是一个智能记忆管理助手。你的任务是分析用户近期的发言记录，更新该用户的长期记忆。

【待更新用户信息】
- 用户名: {user_name}

【当前已有记忆】
1. 核心称谓与铁律区 (不可轻易修改):
{directives_str}

2. 用户画像与偏好摘要:
{profile_str}

【本次新增的用户发言记录】
{messages_str}

【处理要求与铁律保护规则】
1. 【铁律区判定】:
   - 铁律区记录用户的明确称谓要求（如“叫我浩哥”）、强制禁忌或永久性偏好。
   - 必须保持严谨：除非在【本次新增的用户发言记录】中有用户【明确且直接要求修改称谓或设定】的语句（例如“以后别叫我浩哥了，叫我阿浩”），否则【必须原样保留】现有的所有铁律，严禁随意删除、修改或稀释！
   - 如果用户明确提出了新的称谓或新的永久规则，更新或追加到 directives 列表中。
2. 【用户画像与偏好提炼】:
   - 结合新增发言和旧画像，提炼或更新用户的音乐喜好（歌手、风格、常点歌曲）、聊天话题特点、性格互动习惯等。
   - 语言简明扼要，控制在 150 字以内。
3. 【输出格式要求】:
   - 必须且只能输出严格的 JSON 对象，格式如下：
   {{"directives": ["称谓: 浩哥", "..."], "profile": "更新后的画像描述"}}
"""

            payload = {
                "model": resolver.model,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }

            resp_str = await resolver._call_api(payload)
            import json
            resp_data = json.loads(resp_str)
            choices = resp_data.get("choices", [])
            if not choices:
                return False, existing_directives, existing_profile

            content = choices[0].get("message", {}).get("content", "")
            parsed = resolver._extract_json(content)
            if not parsed:
                return False, existing_directives, existing_profile

            raw_directives = parsed.get("directives")
            raw_profile = parsed.get("profile")

            if raw_directives is not None and isinstance(raw_directives, list):
                updated_directives = [str(d).strip() for d in raw_directives if str(d).strip()]
            else:
                updated_directives = existing_directives

            if raw_profile is not None:
                updated_profile = str(raw_profile).strip()
            else:
                updated_profile = existing_profile

            return True, updated_directives, updated_profile

        except Exception as e:
            logger.error(f"Error calling consolidation LLM: {e}")
            return False, existing_directives, existing_profile
