"""`MemoryDistiller` 的 LLM 适配器：把既有 OpenAI 兼容 HTTP 客户端包成记忆提炼。

客户端由组合根注入（当前是 `OpenAICompatibleNaturalLanguageResolver` 传输适配器，
ADR-0006 的提示词与解析规则原样保留）。
"""

import json
import logging
from typing import Any

from ushareiplay.modules.user.ports import MemoryDistiller

logger = logging.getLogger(__name__)


class LLMMemoryDistiller(MemoryDistiller):
    def __init__(self, client: Any, timeout: float = 30.0):
        self._client = client
        self._timeout = timeout

    async def distill(
        self,
        user_name: str,
        existing_directives: list[str],
        existing_profile: str,
        new_messages: list[str],
    ) -> tuple[bool, list[str], str]:
        client = self._client
        if not client or not client.enabled or not client.api_key:
            logger.debug("LLM not enabled/configured for memory consolidation")
            return False, existing_directives, existing_profile

        try:
            directives_str = (
                "\n".join([f"- {d}" for d in existing_directives])
                if existing_directives
                else "无"
            )
            profile_str = existing_profile if existing_profile else "无"
            messages_str = "\n".join(
                [f"{i+1}. {m}" for i, m in enumerate(new_messages)]
            )

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
                "model": client.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            }

            resp_str = await client._call_api(payload, timeout=self._timeout)
            resp_data = json.loads(resp_str)
            choices = resp_data.get("choices", [])
            if not choices:
                return False, existing_directives, existing_profile

            content = choices[0].get("message", {}).get("content", "")
            parsed = client._extract_json(
                content, required_keys=["directives", "profile"]
            )
            if not parsed:
                return False, existing_directives, existing_profile

            raw_directives = parsed.get("directives")
            raw_profile = parsed.get("profile")

            if raw_directives is not None and isinstance(raw_directives, list):
                updated_directives = [
                    str(d).strip() for d in raw_directives if str(d).strip()
                ]
            else:
                updated_directives = existing_directives

            updated_profile = (
                str(raw_profile).strip()
                if raw_profile is not None
                else existing_profile
            )
            return True, updated_directives, updated_profile

        except Exception as error:
            logger.error(
                f"Error calling consolidation LLM (timeout={self._timeout}s): {error}"
            )
            return False, existing_directives, existing_profile
