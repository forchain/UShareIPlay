"""OpenAI-compatible HTTP adapter for natural-language command resolution.

All HTTP and response parsing lives here; the prompt itself is built by the
`ResolveNaturalLanguage` use case. Config keys (`llm.*`: enabled, base_url,
api_key, model, timeout) and the request shape are unchanged (ADR-0003).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from typing import Any, Optional

from ushareiplay.core.chat_intake import format_ai_message
from ushareiplay.modules.command.domain import (
    NaturalLanguageContext,
    NaturalLanguageResult,
)
from ushareiplay.modules.command.ports import NaturalLanguageResolver

logger = logging.getLogger(__name__)


class OpenAICompatibleNaturalLanguageResolver(NaturalLanguageResolver):
    """Resolves a prebuilt prompt through an OpenAI-compatible chat endpoint."""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.base_url = str(cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = str(cfg.get("api_key", "")).strip()
        self.model = str(cfg.get("model", "deepseek-chat"))
        self.timeout = float(cfg.get("timeout", 4.0))

    def _extract_json(self, raw_content: str, required_keys: Optional[list[str]] = None) -> Optional[dict]:
        """Extract and parse JSON object from raw LLM output text."""
        if not raw_content:
            return None
        raw = raw_content.strip()

        # Remove <think>...</think> reasoning tags if emitted by thinking models
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        # Check for markdown code fence
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            match_brace = re.search(r"(\{.*\})", raw, re.DOTALL)
            if match_brace:
                json_str = match_brace.group(1)
            else:
                json_str = raw

        def _matches_schema(parsed_dict: Any) -> bool:
            if not isinstance(parsed_dict, dict):
                return False
            if required_keys:
                return all(key in parsed_dict for key in required_keys)
            return True

        try:
            data = json.loads(json_str)
            if _matches_schema(data):
                return data
        except Exception:
            pass

        # Fallback: search for any standalone valid JSON object
        for chunk in re.findall(r"\{[^{}]*\}", raw):
            try:
                data = json.loads(chunk)
                if _matches_schema(data):
                    return data
            except Exception:
                continue

        logger.debug(f"Failed to parse JSON from LLM output: {raw_content}")
        return None

    def _sync_http_call(self, payload: dict, timeout: Optional[float] = None) -> str:
        """Synchronous HTTP call to OpenAI-compatible endpoint."""
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            url = base
        else:
            url = f"{base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        effective_timeout = float(timeout) if timeout is not None else self.timeout
        with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
            return resp.read().decode("utf-8")

    async def _call_api(self, payload: dict, timeout: Optional[float] = None) -> str:
        """Asynchronous wrapper for API call."""
        return await asyncio.to_thread(self._sync_http_call, payload, timeout=timeout)

    async def resolve(
        self, text: str, context: NaturalLanguageContext
    ) -> Optional[NaturalLanguageResult]:
        """Call the LLM and validate its output into a command/reply result."""
        if not text:
            return None

        payload = {
            "model": context.model,
            "messages": [
                {"role": "system", "content": context.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
        }

        response_json_str = await self._call_api(payload, timeout=context.timeout)
        resp_data = json.loads(response_json_str)
        choices = resp_data.get("choices", [])
        if not choices:
            return None

        content = choices[0].get("message", {}).get("content", "")
        parsed = self._extract_json(content, required_keys=["type", "content"])
        if not parsed:
            return None

        result_type = str(parsed.get("type", "")).strip().lower()
        result_content = str(parsed.get("content", "")).strip()
        if result_type in ("command", "reply") and result_content:
            if result_type == "reply":
                result_content = format_ai_message(result_content)
            return NaturalLanguageResult(type=result_type, content=result_content)

        return None
