"""`UserRepository` 的共享契约场景：内存替身与 Tortoise/SQLite 各跑一遍。"""

from ushareiplay.modules.user.domain import User


async def assert_get_or_create_is_idempotent(repository):
    first = await repository.get_or_create("Alice")
    second = await repository.get_or_create("Alice")

    assert isinstance(first, User)
    assert first.id == second.id
    assert str(first.username) == "Alice"
    assert (first.level, first.heat_value) == (0, 0)
    assert await repository.get_by_id(first.id) == first
    assert await repository.get_by_username("Alice") == first
    assert await repository.get_by_username("missing") is None
    assert await repository.get_by_id(9999) is None


async def assert_alias_resolves_to_canonical(repository):
    canonical = await repository.get_or_create("canonical")
    alias = await repository.get_or_create_raw("avatar")
    assert alias.id != canonical.id

    await repository.set_canonical(alias.id, canonical.id)

    assert await repository.get_by_username("avatar") == User(
        id=alias.id, username="avatar", canonical_user_id=canonical.id
    )
    assert await repository.get_or_create("avatar") == canonical
    assert await repository.get_or_create("canonical") == canonical


async def assert_resolve_canonical_follows_chain_and_falls_back(repository):
    a = await repository.get_or_create_raw("a")
    b = await repository.get_or_create_raw("b")
    c = await repository.get_or_create_raw("c")
    await repository.set_canonical(a.id, b.id)
    await repository.set_canonical(b.id, c.id)
    a = await repository.get_by_id(a.id)

    assert await repository.resolve_canonical(a) == c

    broken = await repository.get_or_create_raw("broken")
    missing = await repository.resolve_canonical(
        User(id=broken.id, username="broken", canonical_user_id=9999)
    )
    assert missing.id == broken.id

    await repository.set_canonical(a.id, b.id)
    await repository.set_canonical(b.id, a.id)
    a = await repository.get_by_id(a.id)
    b = await repository.get_by_id(b.id)
    assert (await repository.resolve_canonical(a)).id == a.id
    assert (await repository.resolve_canonical(b)).id == b.id


async def assert_update_level(repository):
    user = await repository.get_or_create("Bob")

    assert (await repository.update_level(user.id, 4)).level == 4
    assert (await repository.get_or_create("Bob")).level == 4
    assert await repository.update_level(9999, 4) is None


async def assert_update_level_if_lower(repository):
    user = await repository.get_or_create("Carol")

    assert (await repository.update_level_if_lower("Carol", 3)).level == 3
    assert (await repository.update_level_if_lower("Carol", 3)).level == 3
    assert (await repository.update_level_if_lower("Carol", 2)).level == 3
    assert (await repository.get_by_id(user.id)).level == 3


async def assert_record_owner_gift(repository):
    assert (await repository.record_owner_gift("Dave")).level == 4

    high = await repository.get_or_create("Erin")
    await repository.update_level(high.id, 7)
    assert (await repository.record_owner_gift("Erin")).level == 7


async def assert_record_heat_contribution(repository):
    first = await repository.record_heat_contribution("Grace", 6000)
    assert (first.level, first.heat_value) == (5, 6000)

    second = await repository.record_heat_contribution("Grace", 5000)
    assert (second.level, second.heat_value) == (6, 11000)

    third = await repository.record_heat_contribution("Grace", 90000)
    assert (third.level, third.heat_value) == (7, 101000)

    fourth = await repository.record_heat_contribution("Grace", 900000)
    assert (fourth.level, fourth.heat_value) == (8, 1001000)

    owner = await repository.get_or_create("Owner")
    await repository.update_level(owner.id, 9)
    assert (await repository.record_heat_contribution("Owner", 2000000)).level == 9


async def assert_heat_accumulates_on_canonical(repository):
    canonical = await repository.get_or_create("main")
    alias = await repository.get_or_create_raw("alt")
    await repository.set_canonical(alias.id, canonical.id)

    contributed = await repository.record_heat_contribution("alt", 6000)

    assert contributed.id == canonical.id
    assert (contributed.level, contributed.heat_value) == (5, 6000)
    assert (await repository.get_or_create("main")).heat_value == 6000


async def assert_identity_usernames(repository):
    canonical = await repository.get_or_create("canonical")
    avatar = await repository.get_or_create_raw("avatar")
    await repository.set_canonical(avatar.id, canonical.id)

    assert await repository.get_identity_usernames("canonical") == {"canonical", "avatar"}
    assert await repository.get_identity_usernames("avatar") == {"canonical", "avatar"}
    assert await repository.get_identity_usernames("stranger") == {"stranger"}
    assert await repository.get_by_username("stranger") is None
    assert await repository.get_identity_usernames("") == set()

    assert await repository.is_same_identity("canonical", "avatar") is True
    assert await repository.is_same_identity("avatar", "canonical") is True
    assert await repository.is_same_identity("canonical", "stranger") is False
    assert await repository.is_same_identity("", "canonical") is False


async def assert_avatar_and_associated_ids(repository):
    canonical = await repository.get_or_create("canonical")
    avatar = await repository.get_or_create_raw("avatar")
    await repository.set_canonical(avatar.id, canonical.id)

    assert await repository.get_all_avatar_usernames("canonical") == {"canonical", "avatar"}
    assert await repository.get_all_avatar_usernames("avatar") == {"canonical", "avatar"}

    stranger_names = await repository.get_all_avatar_usernames("stranger")
    assert stranger_names == {"stranger"}
    assert await repository.get_by_username("stranger") is not None

    assert set(await repository.get_all_associated_user_ids("avatar")) == {
        canonical.id,
        avatar.id,
    }
