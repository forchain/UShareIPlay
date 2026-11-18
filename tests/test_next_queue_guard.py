"""Next Queue 守护判定（#521）。

守护判定是 `PlaylistSession.check_playlist_protection` 这个公开接缝，因此这里不经过
命令层或播放引擎：直接构造歌单状态、在线列表与分身关系，断言放行/拦截结果。
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from tortoise import Tortoise

from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.room import InfoManager, RoomState
from ushareiplay.adapters.outbound.persistence.models.user import User
from ushareiplay.managers.playlist_session import PlaylistSession
from tests.legacy_state import PresenceTracker

CONFIG = ConfigView({
    "soul": {
        "room_owner": "Joyer",
        "admin_users": ["Outlier", "Chainer"],
        "system_users": ["Timer", "Agent"],
    }
})


@pytest_asyncio.fixture
async def user_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["ushareiplay.adapters.outbound.persistence.models.user"]},
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.fixture
def info_manager():
    for cls in (PlaylistSession, PresenceTracker):
        cls.reset_instance()
    fake_logger = SimpleNamespace(
        info=lambda _msg: None,
        warning=lambda _msg: None,
        error=lambda _msg: None,
    )
    presence = PresenceTracker.initialize()
    presence._logger = fake_logger
    playlist = PlaylistSession.initialize()
    playlist._logger = fake_logger
    return InfoManager(
        room_state=RoomState(),
        presence=presence,
        playlist=playlist,
        logger=fake_logger,
    )


def queue_next(info_manager, *contributors):
    for name in contributors:
        PlaylistSession.instance().record_next(name)


async def add_avatar(canonical, avatar):
    user = await User.create(username=canonical, level=0)
    await User.create(username=avatar, level=0, canonical_user_id=user.id)


@pytest.mark.asyncio
async def test_single_contributor_online_blocks_regular_caller(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result == {"error": "Alice 正在点歌，请等待"}


@pytest.mark.asyncio
async def test_contributor_offline_allows_caller(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_contributor_avatar_online_blocks_caller(user_db, info_manager):
    await add_avatar("Alice", "Alice小号")
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice小号", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result == {"error": "Alice 正在点歌，请等待"}


@pytest.mark.asyncio
async def test_contributor_may_override_own_queue(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Alice", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_contributor_avatar_may_override_own_queue(user_db, info_manager):
    await add_avatar("Alice", "Alice小号")
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Alice小号", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Alice小号", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_human_operator_bypasses_next_queue(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Outlier"])

    result = await PlaylistSession.instance().check_playlist_protection("Outlier", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_multiple_contributors_name_the_online_one(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Alice", "Bob")
    PresenceTracker.instance().update_online_users(["Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Carol", config=CONFIG)

    assert result == {"error": "Bob 正在点歌，请等待"}


@pytest.mark.asyncio
async def test_all_contributors_privileged_is_not_guarded(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    queue_next(info_manager, "Timer", "Agent")
    PresenceTracker.instance().update_online_users(["Timer", "Agent", "Alice"])

    result = await PlaylistSession.instance().check_playlist_protection("Alice", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
async def test_zero_pending_count_allows_even_with_listed_contributors(user_db, info_manager):
    PlaylistSession.instance().player_name = ""
    info_manager.next_queue_contributors.add("Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize("player_name", ["", "Timer"])
async def test_next_queue_guard_is_independent_of_playlist_context(
    user_db, info_manager, player_name
):
    PlaylistSession.instance().player_name = player_name
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result == {"error": "Alice 正在点歌，请等待"}


@pytest.mark.asyncio
async def test_playlist_owner_offline_but_contributor_online_still_blocks(
    user_db, info_manager
):
    PlaylistSession.instance().player_name = "儿童不易"
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result == {"error": "Alice 正在点歌，请等待"}


@pytest.mark.asyncio
async def test_playlist_context_error_wins_when_both_block(user_db, info_manager):
    PlaylistSession.instance().player_name = "儿童不易"
    queue_next(info_manager, "Alice")
    PresenceTracker.instance().update_online_users(["儿童不易", "Alice", "Bob"])

    result = await PlaylistSession.instance().check_playlist_protection("Bob", config=CONFIG)

    assert result == {"error": "儿童不易 正在播放歌单，请等待"}
