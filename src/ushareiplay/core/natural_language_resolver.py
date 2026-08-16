"""Natural Language Command Resolver — Translates natural language utterances to commands/replies via LLM."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NaturalLanguageResult:
    """Frozen result from natural language intent resolution.

    Fields:
        type: 'command' or 'reply'
        content: Translated command string (e.g. ':play 周杰伦 晴天') or chat reply text
    """

    type: str
    content: str


class NaturalLanguageResolver:
    """Resolves natural language requests into structured commands or replies using an LLM."""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.base_url = str(cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        self.api_key = str(cfg.get("api_key", "")).strip()
        self.model = str(cfg.get("model", "deepseek-chat"))
        self.timeout = float(cfg.get("timeout", 4.0))
        self.custom_prompt = str(cfg.get("custom_prompt") or cfg.get("system_prompt") or "").strip()
        system_users_cfg = cfg.get("system_users")
        if system_users_cfg is not None:
            self.system_users = set(system_users_cfg)
        else:
            self.system_users = {"Timer", "Console", "Agent"}

    def _format_player_description(self, player: str, system_users: set[str]) -> str:
        """Format player name, distinguishing system users."""
        if not player:
            return ""
        if player in system_users or player.lower() in {u.lower() for u in system_users}:
            p_lower = player.lower()
            if p_lower == "timer":
                return f"{player} (系统定时器自动播放)"
            elif p_lower == "console":
                return f"{player} (系统控制台/后台指令)"
            elif p_lower == "agent":
                return f"{player} (系统智能体/后台任务)"
            return f"{player} (系统自动化任务/非普通用户)"
        return player

    def _build_system_prompt(
        self,
        user_name: str,
        user_level: int,
        commands_config: list[dict],
        playback_info: Optional[dict] = None,
        room_info: Optional[dict] = None,
    ) -> str:
        """Construct the system prompt with command schemas, user context, playback state, and room state."""
        cmd_lines = []
        for cmd in commands_config or []:
            prefix = cmd.get("prefix", "")
            if not prefix:
                continue
            lvl = cmd.get("level", 0)
            desc = cmd.get("description") or cmd.get("response_template") or prefix
            cmd_lines.append(f"- `:{prefix}` (所需等级: L{lvl}): {desc}")

        cmd_table = "\n".join(cmd_lines) if cmd_lines else "- `:play` (所需等级: L1): 播放指定歌曲"

        playback_lines = []
        playback_desc = "无"
        if playback_info:
            song = playback_info.get("song") or ""
            singer = playback_info.get("singer") or ""
            if song and song != "Unknown":
                playback_desc = f"{song} - {singer}" if (singer and singer != "Unknown") else song
        playback_lines.append(f"- 当前正在播放歌曲: {playback_desc}")

        if playback_info:
            player = playback_info.get("player")
            if player:
                player_desc = self._format_player_description(player, self.system_users)
                playback_lines.append(f"- 当前播放者/点歌人: {player_desc}")

            playlist_name = playback_info.get("playlist_name")
            if playlist_name:
                ptype = playback_info.get("playlist_type") or "歌单"
                if player:
                    is_sys = player in self.system_users or player.lower() in {u.lower() for u in self.system_users}
                    owner_tag = f" (by {player} [系统播放])" if is_sys else f" (by {player})"
                else:
                    owner_tag = ""
                playback_lines.append(f"- 当前播放列表/歌单: [{ptype}] {playlist_name}{owner_tag}")
            else:
                playback_lines.append("- 当前播放列表/歌单: 暂无活跃歌单")

            play_mode = playback_info.get("play_mode")
            if play_mode and play_mode != "未知":
                playback_lines.append(f"- 播放模式: {play_mode}")
        else:
            playback_lines.append("- 当前播放列表/歌单: 暂无活跃歌单")

        playback_section = "\n".join(playback_lines)

        room_desc_lines = []
        if room_info:
            is_guest = room_info.get("is_guest_room", False)
            room_type_str = "他人房间（客房模式，仅支持点歌）" if is_guest else "主房间（宿主模式，支持全部功能）"
            room_desc_lines.append(f"- 房间类型: {room_type_str}")
            room_id = room_info.get("room_id")
            if room_id:
                room_desc_lines.append(f"- 房间ID: {room_id}")
            user_count = room_info.get("user_count")
            if user_count is not None:
                room_desc_lines.append(f"- 在线人数: {user_count}人")
            focus_count = room_info.get("focus_count")
            if focus_count is not None:
                room_desc_lines.append(f"- 专注人数: {focus_count}人")
            rec = room_info.get("recommendation_enabled")
            if rec is not None:
                room_desc_lines.append(f"- 派对推荐: {'开启' if rec else '关闭'}")
        else:
            room_desc_lines.append("- 房间类型: 主房间（宿主模式）")

        room_desc = "\n".join(room_desc_lines)

        custom_section = ""
        if self.custom_prompt:
            custom_section = f"\n\n【用户自定义行为指令 / 补充设定】\n{self.custom_prompt}"

        return f"""你是一个智能派对房间命令解析助手。你的任务是将用户的自然语言转换为标准命令或友好的中文回复。

【当前环境与上下文】
- 发言用户: {user_name}
- 用户权限等级: L{user_level}
{playback_section}
{room_desc}

【可用系统命令列表】
{cmd_table}

【输出规则】
1. 必须且只能输出严格的 JSON 格式，不要包含任何 markdown 代码块标记以外的多余解释。
2. JSON 格式: {{"type": "command" | "reply", "content": "..."}}
3. 如果用户意图为执行某个命令:
   - 若 用户等级 >= 命令所需等级: 输出 {{"type": "command", "content": ":<命令前缀> <参数>"}}，如 {{"type": "command", "content": ":play 周杰伦 晴天"}} 或 {{"type": "command", "content": ":next"}}。
   - 若 用户等级 < 命令所需等级: 输出 {{"type": "reply", "content": "你的权限不足（当前等级 L{user_level}，需要 L<所需等级>），请关注群主或联系房管升级~"}}。
4. 如果用户表达的是代词（如“这首歌”、“重新播放”、“再放一遍”），结合当前正在播放歌曲转译出准确的歌曲命令。
5. 如果用户询问当前房间状态（如房间ID、当前是在主房间还是他人房间、在线人数、推荐状态等），结合【当前环境与上下文】中的房间信息用友好的中文直接回答。
6. 如果用户询问当前播放状态（如“现在是播我的歌单吗”、“现在在播谁的歌/歌单”、“当前播的是什么歌单”、“当前播放模式是什么”等）:
   - 必须对比发言用户与【当前环境与上下文】中的当前播放者/点歌人及歌单信息。
   - 若当前播放者是系统用户（如 Timer、Console、Agent 等系统角色）：必须明确告知当前是由系统（如定时任务、控制台或系统自动化）自动播放，而非普通房间听众点播；若用户询问是否是自己的歌单，明确告知是系统自动播放。
   - 若发言用户与当前播放者一致且有活跃歌单（且非系统用户），明确肯定回复（例如“是的，当前正在播放你的歌单《...》哦~”）。
   - 若发言用户与当前播放者不一致（且播放者为其他普通用户），明确告知当前正在播放的是哪位用户点播的歌/歌单。
   - 若当前暂无活跃歌单或未在播放歌曲，也如实友好回答。
7. 如果用户只是日常打招呼、闲聊、调侃或提问（非命令）:
   - 输出 {{"type": "reply", "content": "<简短友好的中文回复>"}}。
8. 如果用户意图完全无法理解或无法匹配任何操作:
   - 输出 {{"type": "reply", "content": "未能理解你的指令，你可以直接发送 :play 歌名 点歌哦~"}}。{custom_section}
"""

    def _extract_json(self, raw_content: str) -> Optional[dict]:
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

        try:
            data = json.loads(json_str)
            if isinstance(data, dict) and "type" in data and "content" in data:
                return data
        except Exception:
            pass

        # Fallback: search for any standalone valid JSON object matching our schema
        for chunk in re.findall(r"\{[^{}]*\}", raw):
            try:
                data = json.loads(chunk)
                if isinstance(data, dict) and "type" in data and "content" in data:
                    return data
            except Exception:
                continue

        logger.debug(f"Failed to parse JSON from LLM output: {raw_content}")
        return None

    def _sync_http_call(self, payload: dict) -> str:
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

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8")

    async def _call_api(self, payload: dict) -> str:
        """Asynchronous wrapper for API call."""
        return await asyncio.to_thread(self._sync_http_call, payload)

    async def resolve(
        self,
        user_text: str,
        user_name: str,
        user_level: int = 0,
        commands_config: Optional[list[dict]] = None,
        playback_info: Optional[dict] = None,
        room_info: Optional[dict] = None,
    ) -> Optional[NaturalLanguageResult]:
        """Resolve a natural language user utterance into a command or reply.

        Args:
            user_text: Raw natural language text from user
            user_name: Nickname of the user
            user_level: Current level of the user (defaults to 0)
            commands_config: List of command configurations
            playback_info: Active playback information dictionary
            room_info: Active room information dictionary

        Returns:
            NaturalLanguageResult if successfully resolved, or None if disabled/error/timeout.
        """
        if not self.enabled or not self.api_key or not user_text:
            return None

        system_prompt = self._build_system_prompt(
            user_name=user_name,
            user_level=user_level,
            commands_config=commands_config or [],
            playback_info=playback_info,
            room_info=room_info,
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
        }

        try:
            response_json_str = await self._call_api(payload)
            resp_data = json.loads(response_json_str)
            choices = resp_data.get("choices", [])
            if not choices:
                return None

            content = choices[0].get("message", {}).get("content", "")
            parsed = self._extract_json(content)
            if not parsed:
                return None

            result_type = str(parsed.get("type", "")).strip().lower()
            result_content = str(parsed.get("content", "")).strip()
            if result_type in ("command", "reply") and result_content:
                return NaturalLanguageResult(type=result_type, content=result_content)
        except Exception as e:
            logger.warning(f"NaturalLanguageResolver error during resolution: {e}")
            return None

        return None
