"""`KeywordRepository` 契约场景：同一份断言跑在内存替身与 Tortoise/SQLite 上。"""

from ushareiplay.modules.command.domain import KEYWORD_MODE_RANDOM, Keyword


async def assert_create_and_get(repository, users):
    alice = await users.get_or_create("Alice")

    created = await repository.create(
        keyword="k1",
        command=":play 晴天",
        creator_id=alice.id,
        is_public=False,
        mode=KEYWORD_MODE_RANDOM,
    )

    assert isinstance(created, Keyword)
    assert created.keyword == "k1"
    assert created.command == ":play 晴天"
    assert created.mode == KEYWORD_MODE_RANDOM
    assert created.creator_id == alice.id
    assert created.creator_username == "Alice"
    assert created.creator_level == alice.level
    assert created.is_public is False
    assert created.is_config is False
    assert await repository.get_by_keyword("k1") == created
    assert await repository.get_by_keyword("missing") is None

    config_keyword = await repository.create(keyword="help", command=":help")
    assert config_keyword.is_config is True
    assert config_keyword.creator_id is None
    assert config_keyword.is_public is True


async def assert_get_by_keyword_and_username(repository, users):
    alice = await users.get_or_create("Alice")
    bob = await users.get_or_create("Bob")
    await repository.create(keyword="k1", command=":help", creator_id=alice.id)
    await repository.create(keyword="k1", command=":play", creator_id=bob.id)

    found = await repository.get_by_keyword_and_username("k1", "Bob")
    assert found.command == ":play"
    assert found.creator_username == "Bob"
    assert await repository.get_by_keyword_and_username("k1", "Carol") is None


async def assert_find_accessible_keyword(repository, users):
    alice = await users.get_or_create("Alice")
    bob = await users.get_or_create("Bob")
    carol = await users.get_or_create("Carol")

    await repository.create(keyword="public", command=":help", is_public=True)
    assert await repository.find_accessible_keyword("public", "Bob") is not None

    await repository.create(
        keyword="private", command=":help", creator_id=alice.id, is_public=False
    )
    assert await repository.find_accessible_keyword("private", "Alice") is not None
    assert await repository.find_accessible_keyword("private", "Bob") is None

    await repository.grant_users("private", [bob.id, carol.id])
    assert await repository.find_accessible_keyword("private", "Bob") is not None
    assert await repository.find_accessible_keyword("private", "Carol") is not None

    await repository.revoke_users("private", [bob.id])
    assert await repository.find_accessible_keyword("private", "Bob") is None
    assert await repository.find_accessible_keyword("private", "Carol") is not None

    alias = await users.get_or_create_raw("Alice2")
    await users.set_canonical(alias.id, alice.id)
    assert await repository.find_accessible_keyword("private", "Alice2") is not None

    assert await repository.find_accessible_keyword("missing", "Alice") is None


async def assert_grant_and_revoke_filter_ids(repository, users):
    alice = await users.get_or_create("Alice")
    bob = await users.get_or_create("Bob")
    await repository.create(
        keyword="k1", command=":help", creator_id=alice.id, is_public=False
    )

    granted = await repository.grant_users("k1", [bob.id, bob.id, 0, -5])
    assert granted.allowed_user_ids == (bob.id,)

    revoked = await repository.revoke_users("k1", [bob.id])
    assert revoked.allowed_user_ids == ()
    assert await repository.revoke_users("missing", [bob.id]) is None


async def assert_update_publicity(repository, users):
    alice = await users.get_or_create("Alice")
    await repository.create(
        keyword="k1", command=":help", creator_id=alice.id, is_public=False
    )

    updated = await repository.update_publicity("k1", True)
    assert updated.is_public is True
    assert (await repository.get_by_keyword("k1")).is_public is True
    assert await repository.update_publicity("missing", True) is None


async def assert_delete(repository, users):
    alice = await users.get_or_create("Alice")
    await repository.create(keyword="k1", command=":help", creator_id=alice.id)

    assert await repository.delete_by_keyword("k1") is True
    assert await repository.get_by_keyword("k1") is None
    assert await repository.delete_by_keyword("k1") is False


async def assert_delete_config_keywords(repository, users):
    alice = await users.get_or_create("Alice")
    await repository.create(keyword="config-a", command=":help")
    await repository.create(keyword="config-b", command=":help")
    await repository.create(keyword="user", command=":help", creator_id=alice.id)

    assert await repository.delete_config_keywords() == 2
    assert [entry.keyword for entry in await repository.list_all()] == ["user"]
    assert await repository.delete_config_keywords() == 0


async def assert_lists(repository, users):
    alice = await users.get_or_create("Alice")
    bob = await users.get_or_create("Bob")
    await repository.create(keyword="a", command=":help", creator_id=alice.id)
    await repository.create(keyword="b", command=":help", creator_id=bob.id)
    await repository.create(keyword="c", command=":help")

    assert [entry.keyword for entry in await repository.list_by_creator("Alice")] == ["a"]
    assert sorted(entry.keyword for entry in await repository.list_all()) == ["a", "b", "c"]
