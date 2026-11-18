"""用户命名用例：可见昵称解析、别名绑定、等级读写。"""

import pytest

from ushareiplay.modules.shared.roles import RolePolicy
from ushareiplay.modules.user.domain import (
    AliasCycleError,
    InvalidLevelError,
    MissingCallerError,
    NewLevelNotBelowCallerError,
    TargetNotBelowCallerError,
)
from ushareiplay.modules.user.use_cases import (
    BindAlias,
    GetLevel,
    ResolveVisibleUsername,
    SetLevel,
)
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


class RecordingLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


@pytest.fixture
def repository():
    return InMemoryUserRepository()


@pytest.fixture
def policy():
    return RolePolicy(
        {
            "room_owner": "Owner",
            "admin_users": ["Admin"],
            "system_users": ["Timer"],
        }
    )


def _resolver(repository, online, logger=None):
    online = set(online)
    return ResolveVisibleUsername(
        users=repository,
        is_online=lambda name: name in online,
        online_users=lambda: set(online),
        logger=logger,
    )


async def test_resolve_returns_the_name_already_online(repository):
    resolver = _resolver(repository, {"Alice"})

    assert str(await resolver.execute("Alice")) == "Alice"
    assert str(await resolver.execute("")) == ""


async def test_resolve_maps_canonical_to_the_online_avatar(repository):
    canonical = await repository.get_or_create("main")
    avatar = await repository.get_or_create_raw("avatar")
    await repository.set_canonical(avatar.id, canonical.id)
    resolver = _resolver(repository, {"avatar"})

    assert str(await resolver.execute("main")) == "avatar"
    assert str(await resolver.execute("avatar")) == "avatar"


async def test_resolve_returns_the_input_when_no_identity_member_is_online(repository):
    canonical = await repository.get_or_create("main")
    avatar = await repository.get_or_create_raw("avatar")
    await repository.set_canonical(avatar.id, canonical.id)
    resolver = _resolver(repository, set())

    assert str(await resolver.execute("main")) == "main"
    assert str(await resolver.execute("stranger")) == "stranger"


async def test_resolve_uses_stable_order_when_several_avatars_are_online(repository):
    canonical = await repository.get_or_create("main")
    for name in ("zebra", "ant"):
        avatar = await repository.get_or_create_raw(name)
        await repository.set_canonical(avatar.id, canonical.id)
    logger = RecordingLogger()
    resolver = _resolver(repository, {"zebra", "ant"}, logger)

    assert str(await resolver.execute("main")) == "ant"
    assert logger.messages == ["多个分身同时在线 ['ant', 'zebra']，按稳定顺序使用 ant 作为可见昵称"]


async def test_resolve_falls_back_to_the_input_when_lookup_fails():
    class FailingRepository(InMemoryUserRepository):
        async def get_identity_usernames(self, username):
            raise RuntimeError("db down")

    resolver = _resolver(FailingRepository(), set())

    assert str(await resolver.execute("main")) == "main"


async def test_bind_alias_resolves_the_target_to_canonical(repository):
    canonical = await repository.get_or_create("main")
    other = await repository.get_or_create_raw("other")
    await repository.set_canonical(other.id, canonical.id)

    bound = await BindAlias(repository).execute("avatar", "other")

    assert bound == canonical
    assert await repository.get_or_create("avatar") == canonical


async def test_bind_alias_rejects_binding_a_user_to_itself(repository):
    await repository.get_or_create("main")

    with pytest.raises(AliasCycleError):
        await BindAlias(repository).execute("main", "main")


async def test_get_level_returns_the_canonical_record(repository):
    canonical = await repository.get_or_create("main")
    await repository.update_level(canonical.id, 3)

    user = await GetLevel(repository).execute("main")

    assert str(user.username) == "main"
    assert user.level == 3


async def test_set_level_lets_a_human_operator_set_any_level(repository, policy):
    target = await repository.get_or_create("target")

    updated = await SetLevel(repository, policy).execute("Admin", "target", 9)

    assert updated.id == target.id
    assert updated.level == 9


async def test_set_level_requires_a_verifiable_caller(repository, policy):
    await repository.get_or_create("target")

    with pytest.raises(MissingCallerError):
        await SetLevel(repository, policy).execute("", "target", 3)


async def test_set_level_rejects_target_at_or_above_the_caller(repository, policy):
    caller = await repository.get_or_create("caller")
    await repository.update_level(caller.id, 3)
    target = await repository.get_or_create("target")
    await repository.update_level(target.id, 3)

    with pytest.raises(TargetNotBelowCallerError) as error:
        await SetLevel(repository, policy).execute("caller", "target", 1)

    assert (error.value.target_level, error.value.caller_level) == (3, 3)


async def test_set_level_rejects_new_level_at_or_above_the_caller(repository, policy):
    caller = await repository.get_or_create("caller")
    await repository.update_level(caller.id, 3)
    await repository.get_or_create("target")

    with pytest.raises(NewLevelNotBelowCallerError) as error:
        await SetLevel(repository, policy).execute("caller", "target", 3)

    assert (error.value.new_level, error.value.caller_level) == (3, 3)


async def test_set_level_rejects_out_of_range(repository, policy):
    with pytest.raises(InvalidLevelError):
        await SetLevel(repository, policy).execute("Admin", "target", 10)
