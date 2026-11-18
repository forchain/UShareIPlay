"""关键字用例：CRUD/ACL、配置加载、执行与自然语言兜底的接缝测试。"""

from types import SimpleNamespace

import pytest

from ushareiplay.adapters.inbound.runtime.chat_intake import ChatIntakeKind, ChatIntakeResult
from ushareiplay.modules.command.domain import (
    KEYWORD_MODE_RANDOM,
    ConfigKeywordImmutable,
    KeywordAlreadyPublic,
    KeywordEmpty,
    KeywordNotPublic,
    KeywordNotFound,
    MissingGrantees,
    NotKeywordOwner,
    NaturalLanguageResult,
    UserNotOnline,
)
from ushareiplay.modules.command.use_cases import KeywordUseCases
from tests.fakes.in_memory_keyword_repository import InMemoryKeywordRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


class _Presence:
    def __init__(self, online=None):
        self.online = set(online or [])

    def is_user_online(self, username):
        return username in self.online


class _Queue:
    def __init__(self):
        self.messages = []

    async def enqueue(self, content, *, nickname, sleep_exempt):
        self.messages.append(
            SimpleNamespace(content=content, nickname=nickname, sleep_exempt=sleep_exempt)
        )


class _ChatLogs:
    def __init__(self):
        self.entries = []

    async def record(self, username, content):
        self.entries.append((username, content))


class _ConfigSource:
    def __init__(self, data):
        self.data = data

    def load(self):
        return self.data


class _Fallback:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def resolve(self, *, user_text, user_name, user_level):
        self.calls.append((user_text, user_name, user_level))
        return self.result


@pytest.fixture
def keyword_env():
    users = InMemoryUserRepository()
    repository = InMemoryKeywordRepository(users)
    env = SimpleNamespace(
        users=users,
        repository=repository,
        presence=_Presence(),
        queue=_Queue(),
        chat_logs=_ChatLogs(),
        config_source=_ConfigSource({}),
        fallback=_Fallback(),
    )

    def build(fallback=None, config_source=None, chooser=None):
        kwargs = {}
        if chooser is not None:
            kwargs["command_chooser"] = chooser
        return KeywordUseCases(
            repository=repository,
            users=users,
            presence=env.presence,
            queue=env.queue,
            chat_logs=env.chat_logs,
            config_source=config_source or env.config_source,
            fallback=fallback or env.fallback,
            **kwargs,
        )

    env.build = build
    return env


async def test_load_keywords_from_config_replaces_config_rows_and_supports_synonyms(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    await keyword_env.repository.create("user-key", ":help", creator_id=alice.id)
    await keyword_env.repository.create("stale-config", ":help")
    use_cases = keyword_env.build(
        config_source=_ConfigSource(
            {
                "default_keyword": {"command": ":play {params}"},
                "keywords": [
                    {
                        "keyword": "粤语|粤语歌单",
                        "command": ":playlist 粤语经典",
                        "is_public": True,
                        "mode": "sequence",
                    },
                    {
                        "keyword": "随机",
                        "command": ":a;:b",
                        "is_public": False,
                        "mode": "random",
                    },
                ],
            }
        )
    )

    await use_cases.load_keywords_from_config()

    rows = {row.keyword: row for row in await keyword_env.repository.list_all()}
    assert set(rows) == {"user-key", "粤语", "粤语歌单", "随机"}
    assert rows["粤语"].is_config is True
    assert rows["粤语"].is_public is True
    assert rows["随机"].is_public is False
    assert rows["随机"].mode == KEYWORD_MODE_RANDOM


async def test_add_keyword_requires_online_user(keyword_env):
    use_cases = keyword_env.build()
    with pytest.raises(UserNotOnline):
        await use_cases.add_keyword("Alice", "晚安", ":play 晚安", True)


async def test_add_keyword_rejects_empty_keyword(keyword_env):
    keyword_env.presence.online.add("Alice")
    use_cases = keyword_env.build()
    with pytest.raises(KeywordEmpty):
        await use_cases.add_keyword("Alice", " | ", ":play 晚安", True)


async def test_add_keyword_reports_added_overwritten_and_rejected(keyword_env):
    keyword_env.presence.online.add("Alice")
    alice = await keyword_env.users.get_or_create("Alice")
    await keyword_env.users.update_level(alice.id, 3)
    bob = await keyword_env.users.get_or_create("Bob")
    await keyword_env.users.update_level(bob.id, 5)
    await keyword_env.repository.create("config-kw", ":help")
    await keyword_env.repository.create("high-kw", ":help", creator_id=bob.id)
    await keyword_env.repository.create("same-kw", ":help", creator_id=alice.id)
    use_cases = keyword_env.build()

    message = await use_cases.add_keyword(
        "Alice", "new-kw|config-kw|high-kw|same-kw", ":play 晴天", True, "sequence"
    )

    assert message == (
        "成功添加公开关键字(顺序模式): new-kw, same-kw\n"
        "覆盖了关键字: same-kw\n"
        "添加失败: config-kw(配置关键字不可覆盖), high-kw(已被更高等级用户 Bob 创建)"
    )


async def test_add_keyword_uses_private_and_random_labels(keyword_env):
    keyword_env.presence.online.add("Alice")
    use_cases = keyword_env.build()

    message = await use_cases.add_keyword("Alice", "晚安", ":play 晚安", False, "random")

    assert message == "成功添加私有关键字(随机模式): 晚安"


async def test_update_publicity_rules_and_toggle(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    bob = await keyword_env.users.get_or_create("Bob")
    await keyword_env.repository.create("config-kw", ":help")
    await keyword_env.repository.create("alice-kw", ":help", creator_id=alice.id, is_public=False)
    await keyword_env.repository.create("bob-kw", ":help", creator_id=bob.id, is_public=False)
    use_cases = keyword_env.build()

    with pytest.raises(KeywordNotFound):
        await use_cases.update_keyword_publicity("Alice", "missing", True)
    with pytest.raises(ConfigKeywordImmutable):
        await use_cases.update_keyword_publicity("Alice", "config-kw", True)
    with pytest.raises(NotKeywordOwner):
        await use_cases.update_keyword_publicity("Alice", "bob-kw", True)

    assert await use_cases.update_keyword_publicity("Alice", "alice-kw", None) == (
        '关键字 "alice-kw" 已设置为公开'
    )
    assert (await keyword_env.repository.get_by_keyword("alice-kw")).is_public is True
    assert await use_cases.update_keyword_publicity("Alice", "alice-kw", False) == (
        '关键字 "alice-kw" 已设置为私有'
    )


async def test_delete_keyword_rules(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    bob = await keyword_env.users.get_or_create("Bob")
    await keyword_env.repository.create("config-kw", ":help")
    await keyword_env.repository.create("alice-kw", ":help", creator_id=alice.id)
    await keyword_env.repository.create("bob-kw", ":help", creator_id=bob.id)
    use_cases = keyword_env.build()

    with pytest.raises(KeywordNotFound):
        await use_cases.delete_keyword("Alice", "missing")
    with pytest.raises(ConfigKeywordImmutable):
        await use_cases.delete_keyword("Alice", "config-kw")
    with pytest.raises(NotKeywordOwner):
        await use_cases.delete_keyword("Alice", "bob-kw")

    assert await use_cases.delete_keyword("Alice", "alice-kw") == '成功删除关键字 "alice-kw"'
    assert await keyword_env.repository.get_by_keyword("alice-kw") is None


async def test_grant_and_revoke_rules(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    bob = await keyword_env.users.get_or_create("Bob")
    await keyword_env.repository.create("config-kw", ":help")
    await keyword_env.repository.create("public-kw", ":help", creator_id=alice.id, is_public=True)
    await keyword_env.repository.create("alice-kw", ":help", creator_id=alice.id, is_public=False)
    await keyword_env.repository.create("bob-kw", ":help", creator_id=bob.id, is_public=False)
    use_cases = keyword_env.build()

    with pytest.raises(KeywordNotFound):
        await use_cases.grant_keyword_access("Alice", "missing", "Bob")
    with pytest.raises(ConfigKeywordImmutable):
        await use_cases.grant_keyword_access("Alice", "config-kw", "Bob")
    with pytest.raises(KeywordAlreadyPublic):
        await use_cases.grant_keyword_access("Alice", "public-kw", "Bob")
    with pytest.raises(NotKeywordOwner):
        await use_cases.grant_keyword_access("Alice", "bob-kw", "Bob")
    with pytest.raises(MissingGrantees):
        await use_cases.grant_keyword_access("Alice", "alice-kw", " | ")

    assert await use_cases.grant_keyword_access("Alice", "alice-kw", "Bob|Carol") == (
        '已授权关键字 "alice-kw" 给: Bob, Carol'
    )
    assert (await keyword_env.repository.get_by_keyword("alice-kw")).allowed_user_ids == (
        bob.id,
        (await keyword_env.users.get_or_create("Carol")).id,
    )

    with pytest.raises(KeywordNotPublic):
        await use_cases.revoke_keyword_access("Alice", "public-kw", "Bob")
    with pytest.raises(MissingGrantees):
        await use_cases.revoke_keyword_access("Alice", "alice-kw", "")

    assert await use_cases.revoke_keyword_access("Alice", "alice-kw", "Bob") == (
        '已取消授权关键字 "alice-kw" 对: Bob'
    )


async def test_find_keyword_respects_acl(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    await keyword_env.repository.create("private", ":help", creator_id=alice.id, is_public=False)
    use_cases = keyword_env.build()

    assert await use_cases.find_keyword("private", "Alice") is not None
    assert await use_cases.find_keyword("private", "Bob") is None


async def test_execute_keyword_renders_placeholders_and_keeps_sleep_exempt_default(keyword_env):
    use_cases = keyword_env.build()
    keyword = SimpleNamespace(keyword="520", command=":play {params} {user_name}", mode="sequence")

    await use_cases.execute_keyword(keyword, "Alice", params="晴天")

    assert len(keyword_env.queue.messages) == 1
    queued = keyword_env.queue.messages[0]
    assert queued.content == ":play 晴天 Alice"
    assert queued.nickname == "Alice"
    assert queued.sleep_exempt is False


async def test_execute_keyword_random_mode_uses_chooser(keyword_env):
    use_cases = keyword_env.build(chooser=lambda candidates: candidates[-1])
    keyword = SimpleNamespace(keyword="r", command=":a;:b;:c", mode="random")

    await use_cases.execute_keyword(keyword, "Alice")

    assert keyword_env.queue.messages[0].content == ":c"


async def test_dispatch_mention_prefers_keyword_over_fallback(keyword_env):
    keyword_env.presence.online.add("Alice")
    alice = await keyword_env.users.get_or_create("Alice")
    await keyword_env.repository.create("520", ":play 晴天", creator_id=alice.id, is_public=True)
    fallback = _Fallback(NaturalLanguageResult(type="reply", content="不该出现"))
    use_cases = keyword_env.build(fallback=fallback)
    result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION, nickname="Alice", text="520", params=""
    )

    await use_cases.dispatch_mention(result, sleep_exempt=True)

    assert fallback.calls == []
    assert [message.content for message in keyword_env.queue.messages] == [":play 晴天"]


async def test_dispatch_mention_falls_back_to_natural_language(keyword_env):
    alice = await keyword_env.users.get_or_create("Alice")
    await keyword_env.users.update_level(alice.id, 4)
    fallback = _Fallback(NaturalLanguageResult(type="command", content=":play 周杰伦 晴天"))
    use_cases = keyword_env.build(fallback=fallback)
    result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Alice",
        text="放首歌",
        params="",
    )

    await use_cases.dispatch_mention(result, sleep_exempt=True)

    assert fallback.calls == [("放首歌", "Alice", 4)]
    assert keyword_env.queue.messages[0].content == ":play 周杰伦 晴天"
    assert keyword_env.queue.messages[0].sleep_exempt is True
    assert keyword_env.chat_logs.entries == [("Alice", "放首歌")]


async def test_dispatch_mention_falls_back_to_default_keyword(keyword_env):
    fallback = _Fallback(None)
    use_cases = keyword_env.build(
        fallback=fallback,
        config_source=_ConfigSource(
            {"default_keyword": {"command": ":help {user_name} {params}"}, "keywords": []}
        ),
    )
    await use_cases.load_keywords_from_config()
    result = ChatIntakeResult(
        kind=ChatIntakeKind.KEYWORD_MENTION,
        nickname="Bob",
        text="未知",
        params="晚安",
    )

    await use_cases.dispatch_mention(result, sleep_exempt=True)

    assert keyword_env.queue.messages[0].content == ":help Bob 晚安"


async def test_default_keyword_is_silent_when_not_configured(keyword_env):
    use_cases = keyword_env.build()

    await use_cases.execute_default_keyword("Alice", params="x")

    assert keyword_env.queue.messages == []
