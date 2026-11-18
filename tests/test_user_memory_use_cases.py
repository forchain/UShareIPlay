"""用户记忆用例：短期聊天记录、长期记忆注入与 ADR-0006 沉淀语义。"""

import asyncio
import json
from datetime import datetime

from ushareiplay.adapters.outbound.llm.memory_distiller import LLMMemoryDistiller
from ushareiplay.modules.user.domain import MemorySettings
from ushareiplay.modules.user.use_cases import UserMemoryService
from tests.fakes.in_memory_chat_log_repository import InMemoryChatLogRepository
from tests.fakes.in_memory_memory_distiller import InMemoryMemoryDistiller
from tests.fakes.in_memory_user_memory_repository import InMemoryUserMemoryRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


class RecordingLogger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []
        self.error_messages = []
        self.debug_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)

    def error(self, message):
        self.error_messages.append(message)

    def debug(self, message):
        self.debug_messages.append(message)


def build_service(settings=None, distiller=None):
    users = InMemoryUserRepository()
    members = InMemoryUserMemoryRepository()
    chat_logs = InMemoryChatLogRepository(members)
    distiller = distiller or InMemoryMemoryDistiller()
    service = UserMemoryService(
        users=users,
        memories=members,
        chat_logs=chat_logs,
        distiller=distiller,
        settings=settings or MemorySettings(min_messages=3, worker_delay=0),
        logger=RecordingLogger(),
    )
    return service, users, members, chat_logs, distiller


async def _seed_logs(chat_logs, user_id, count):
    for index in range(count):
        await chat_logs.create(user_id, f"消息 {index}")


async def test_record_chat_resolves_alias_to_canonical_user():
    service, users, _members, chat_logs, _distiller = build_service()
    canonical = await users.get_or_create("main")
    alias = await users.get_or_create_raw("alt")
    await users.set_canonical(alias.id, canonical.id)

    entry = await service.record_chat("alt", "放首晴天")

    assert entry.user_id == canonical.id
    assert [log.content for log in await chat_logs.unconsolidated_logs(canonical.id)] == [
        "放首晴天"
    ]


async def test_record_chat_is_skipped_when_disabled_or_blank():
    service, users, _members, chat_logs, _distiller = build_service(
        settings=MemorySettings(enabled=False)
    )
    user = await users.get_or_create("alice")

    assert await service.record_chat("alice", "你好") is None
    assert await service.record_chat("", "你好") is None
    assert await chat_logs.unconsolidated_logs(user.id) == []


async def test_dialogue_context_keeps_long_term_behind_level_threshold():
    service, users, members, chat_logs, _distiller = build_service(
        settings=MemorySettings(min_messages=3, min_level_for_long_term=20)
    )
    user = await users.get_or_create("low_level_user")
    await members.update(
        user.id,
        directives=["称谓: 小五哥"],
        profile="喜欢二次元歌曲",
        consolidated_at=datetime(2025, 1, 1),
    )
    await chat_logs.create(user.id, "放首千本樱")

    context = await service.dialogue_context("low_level_user", user_level=5)

    assert context["directives"] == []
    assert context["profile"] == ""
    assert context["short_term_chats"] == ["放首千本樱"]


async def test_dialogue_context_loads_long_term_at_threshold():
    service, users, members, chat_logs, _distiller = build_service()
    user = await users.get_or_create("vip_user")
    await members.update(
        user.id,
        directives=["称谓: 浩哥", "硬性偏好: 喜好周杰伦"],
        profile="资深房管，偏好华语流行",
        consolidated_at=datetime(2025, 1, 1),
    )
    await chat_logs.create(user.id, "来首晴天")

    context = await service.dialogue_context("vip_user", user_level=20)

    assert context["directives"] == ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"]
    assert context["profile"] == "资深房管，偏好华语流行"
    assert context["short_term_chats"] == ["来首晴天"]


async def test_dialogue_context_custom_threshold_loads_long_term_for_level_zero():
    service, users, members, chat_logs, _distiller = build_service(
        settings=MemorySettings(min_level_for_long_term=0)
    )
    user = await users.get_or_create("guest_user")
    await members.update(
        user.id,
        directives=["称谓: 新朋友"],
        profile="新访客",
        consolidated_at=datetime(2025, 1, 1),
    )
    await chat_logs.create(user.id, "你好")

    context = await service.dialogue_context("guest_user", user_level=0)

    assert context["directives"] == ["称谓: 新朋友"]
    assert context["profile"] == "新访客"
    assert context["short_term_chats"] == ["你好"]


async def test_dialogue_context_empty_state():
    service, users, _members, _chat_logs, _distiller = build_service()
    await users.get_or_create("guest_user")

    context = await service.dialogue_context("guest_user", user_level=0)

    assert context == {
        "directives": [],
        "profile": "",
        "short_term_chats": [],
        "last_consolidated_at": None,
    }


def test_memory_settings_defaults_match_runtime_config():
    settings = MemorySettings()

    assert settings.enabled is True
    assert settings.min_messages == 10
    assert settings.min_level_for_long_term == 20
    assert settings.worker_delay == 1.0
    assert settings.timeout == 30.0


async def test_consolidation_below_threshold_skips_distiller():
    service, users, members, chat_logs, distiller = build_service()
    user = await users.get_or_create("alice")
    await _seed_logs(chat_logs, user.id, 2)

    assert await service.consolidate_user("alice") is False
    assert distiller.calls == []
    assert await members.get(user.id) is None


async def test_consolidation_success_advances_cursor_and_updates_memory():
    distiller = InMemoryMemoryDistiller(
        (True, ["称谓: 浩哥", "硬性偏好: 喜好摇滚乐"], "喜欢华语流行与摇滚乐")
    )
    service, users, members, chat_logs, _distiller = build_service(distiller=distiller)
    user = await users.get_or_create("bob")
    await members.update(
        user.id,
        directives=["称谓: 浩哥"],
        profile="喜欢华语流行",
        consolidated_at=datetime(2025, 1, 1),
    )
    await _seed_logs(chat_logs, user.id, 3)

    assert await service.consolidate_user("bob") is True

    memory = await members.get(user.id)
    assert memory.directives == ["称谓: 浩哥", "硬性偏好: 喜好摇滚乐"]
    assert memory.profile == "喜欢华语流行与摇滚乐"
    assert memory.last_consolidated_at is not None
    assert await chat_logs.count_unconsolidated(
        user.id, since=memory.last_consolidated_at
    ) == 0
    assert distiller.calls == [
        {
            "user_name": "bob",
            "existing_directives": ["称谓: 浩哥"],
            "existing_profile": "喜欢华语流行",
            "new_messages": ["消息 0", "消息 1", "消息 2"],
        }
    ]


async def test_consolidation_failure_retains_cursor_and_memory():
    service, users, members, chat_logs, _distiller = build_service(
        distiller=InMemoryMemoryDistiller((False, ["称谓: 查理"], "老用户"))
    )
    user = await users.get_or_create("charlie")
    original_time = datetime(2026, 1, 1, 12, 0, 0)
    await members.update(
        user.id,
        directives=["称谓: 查理"],
        profile="老用户",
        consolidated_at=original_time,
    )
    await _seed_logs(chat_logs, user.id, 4)

    assert await service.consolidate_user("charlie") is False

    memory = await members.get(user.id)
    assert memory.last_consolidated_at == original_time
    assert memory.directives == ["称谓: 查理"]


async def test_global_sweep_consolidates_only_eligible_users(monkeypatch):
    service, users, _members, chat_logs, _distiller = build_service()
    for name, count in (("user_1", 4), ("user_2", 1), ("user_3", 5)):
        user = await users.get_or_create(name)
        await _seed_logs(chat_logs, user.id, count)

    consolidated = []

    async def record(username):
        consolidated.append(username)
        return True

    monkeypatch.setattr(service, "consolidate_user", record)

    await service.consolidate_all_eligible()

    assert "user_1" in consolidated
    assert "user_3" in consolidated
    assert "user_2" not in consolidated


async def test_worker_loop_debounces_rapid_schedules(monkeypatch):
    service, _users, _members, _chat_logs, _distiller = build_service(
        settings=MemorySettings(worker_delay=0.01, debounce_interval=2.0)
    )

    processed = []

    async def record(username):
        processed.append(username)
        return True

    monkeypatch.setattr(service, "consolidate_user", record)

    await service.start()
    try:
        service.schedule_user("david")
        service.schedule_user("david")
        await asyncio.sleep(0.1)
    finally:
        await service.stop()

    assert processed == ["david"]


def test_memory_settings_read_the_llm_memory_section_from_the_view():
    from ushareiplay.modules.shared.config import ConfigView

    settings = MemorySettings.from_config(
        ConfigView(
            {
                "llm": {
                    "memory": {
                        "enabled": False,
                        "min_messages": 3,
                        "min_level_for_long_term": 42,
                        "timeout": 12.5,
                    }
                }
            }
        )
    )

    assert settings.enabled is False
    assert settings.min_messages == 3
    assert settings.min_level_for_long_term == 42
    assert settings.timeout == 12.5


class FakeLLMClient:
    def __init__(self, content):
        self.enabled = True
        self.api_key = "test-key"
        self.model = "deepseek-chat"
        self._content = content
        self.payload = None
        self.timeout = None

    async def _call_api(self, payload, timeout=None):
        self.payload = payload
        self.timeout = timeout
        return json.dumps({"choices": [{"message": {"content": self._content}}]})

    def _extract_json(self, raw_content, required_keys=None):
        parsed = json.loads(raw_content)
        if required_keys and not all(key in parsed for key in required_keys):
            return None
        return parsed


async def test_llm_distiller_forwards_timeout_and_parses_memory():
    client = FakeLLMClient(
        json.dumps({"directives": ["称谓: 浩哥"], "profile": "喜欢流行"})
    )
    distiller = LLMMemoryDistiller(client, timeout=45.0)

    success, directives, profile = await distiller.distill(
        user_name="test_user",
        existing_directives=[],
        existing_profile="",
        new_messages=["消息1", "消息2"],
    )

    assert success is True
    assert directives == ["称谓: 浩哥"]
    assert profile == "喜欢流行"
    assert client.timeout == 45.0
    assert client.payload["model"] == "deepseek-chat"
    assert "消息2" in client.payload["messages"][0]["content"]


async def test_llm_distiller_returns_original_memory_when_not_configured():
    client = FakeLLMClient("{}")
    client.enabled = False
    distiller = LLMMemoryDistiller(client)

    success, directives, profile = await distiller.distill(
        user_name="u",
        existing_directives=["保持"],
        existing_profile="旧画像",
        new_messages=["新消息"],
    )

    assert (success, directives, profile) == (False, ["保持"], "旧画像")
    assert client.payload is None
