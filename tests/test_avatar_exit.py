"""
分身退出事件聚合测试
验证：只有当主账号 + 全部别名都不在线时，才触发退出事件
"""
import pytest
import pytest_asyncio
from tortoise import Tortoise

from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.models.user import User


@pytest_asyncio.fixture
async def user_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["ushareiplay.models.user"]},
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_get_all_avatar_usernames(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    await User.create(username="小M", level=0, canonical_user_id=canonical.id)

    result = await UserDAO.get_all_avatar_usernames("小明")

    assert result == {"小明", "明明", "小M"}


@pytest.mark.asyncio
async def test_no_leave_if_alias_still_online(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)

    online_users = {"小明", "张三"}
    all_avatars = await UserDAO.get_all_avatar_usernames("明明")
    still_online = all_avatars & online_users

    assert len(still_online) != 0


@pytest.mark.asyncio
async def test_leave_when_all_avatars_offline(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)

    online_users = {"张三", "李四"}
    all_avatars = await UserDAO.get_all_avatar_usernames("明明")
    still_online = all_avatars & online_users

    assert len(still_online) == 0


@pytest.mark.asyncio
async def test_no_aliases_user_triggers_immediately(user_db):
    await User.create(username="张三", level=0)

    online_users = {"李四"}
    all_avatars = await UserDAO.get_all_avatar_usernames("张三")
    still_online = all_avatars & online_users

    assert len(still_online) == 0


@pytest.mark.asyncio
async def test_alias_queried_resolves_to_canonical_group(user_db):
    canonical = await User.create(username="小明", level=0)
    await User.create(username="明明", level=0, canonical_user_id=canonical.id)
    await User.create(username="小M", level=0, canonical_user_id=canonical.id)

    result = await UserDAO.get_all_avatar_usernames("明明")

    assert "小明" in result
    assert "明明" in result
    assert "小M" in result
    assert len(result) == 3
