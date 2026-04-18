"""
分身退出事件聚合测试
验证：只有当主账号 + 全部别名都不在线时，才触发退出事件
"""
import asyncio
from tortoise import Tortoise
from ushareiplay.models.user import User
from ushareiplay.dal.user_dao import UserDAO


async def setup_db():
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["ushareiplay.models.user"]},
    )
    await Tortoise.generate_schemas()


async def teardown_db():
    await Tortoise.close_connections()


async def test_get_all_avatar_usernames():
    """主账号 + 全部别名的 username 集合"""
    await setup_db()
    try:
        canonical = await User.create(username="小明", level=0)
        await User.create(username="明明", level=0, canonical_user_id=canonical.id)
        await User.create(username="小M", level=0, canonical_user_id=canonical.id)

        result = await UserDAO.get_all_avatar_usernames("小明")
        assert result == {"小明", "明明", "小M"}, f"Expected all avatars, got: {result}"
        print("PASS: test_get_all_avatar_usernames")
    finally:
        await teardown_db()


async def test_no_leave_if_alias_still_online():
    """某分身退出，但另一分身仍在线 → 不触发 user_leave"""
    await setup_db()
    try:
        canonical = await User.create(username="小明", level=0)
        await User.create(username="明明", level=0, canonical_user_id=canonical.id)

        # 模拟在线集合：明明已离线，但小明还在线
        online_users = {"小明", "张三"}

        all_avatars = await UserDAO.get_all_avatar_usernames("明明")
        still_online = all_avatars & online_users
        should_trigger = len(still_online) == 0

        assert not should_trigger, "应该不触发退出事件，小明仍在线"
        print("PASS: test_no_leave_if_alias_still_online")
    finally:
        await teardown_db()


async def test_leave_when_all_avatars_offline():
    """主账号 + 全部别名都离线 → 触发 user_leave"""
    await setup_db()
    try:
        canonical = await User.create(username="小明", level=0)
        await User.create(username="明明", level=0, canonical_user_id=canonical.id)

        online_users = {"张三", "李四"}  # 小明和明明都不在线

        all_avatars = await UserDAO.get_all_avatar_usernames("明明")
        still_online = all_avatars & online_users
        should_trigger = len(still_online) == 0

        assert should_trigger, "全部分身都离线，应该触发退出事件"
        print("PASS: test_leave_when_all_avatars_offline")
    finally:
        await teardown_db()


async def test_no_aliases_user_triggers_immediately():
    """没有分身的普通用户离开 → 直接触发（行为不变）"""
    await setup_db()
    try:
        await User.create(username="张三", level=0)  # 无别名

        online_users = {"李四"}  # 张三已离线

        all_avatars = await UserDAO.get_all_avatar_usernames("张三")
        still_online = all_avatars & online_users
        should_trigger = len(still_online) == 0

        assert should_trigger, "无分身的普通用户离开应立即触发"
        print("PASS: test_no_aliases_user_triggers_immediately")
    finally:
        await teardown_db()


async def test_alias_queried_resolves_to_canonical_group():
    """通过别名查询，返回的集合仍包含主账号和其他别名"""
    await setup_db()
    try:
        canonical = await User.create(username="小明", level=0)
        await User.create(username="明明", level=0, canonical_user_id=canonical.id)
        await User.create(username="小M", level=0, canonical_user_id=canonical.id)

        # 用别名 "明明" 查询
        result = await UserDAO.get_all_avatar_usernames("明明")
        assert "小明" in result, "主账号应在结果中"
        assert "明明" in result, "查询用的别名应在结果中"
        assert "小M" in result, "其他别名应在结果中"
        assert len(result) == 3, f"结果应有3个成员，实际: {result}"
        print("PASS: test_alias_queried_resolves_to_canonical_group")
    finally:
        await teardown_db()


if __name__ == "__main__":
    asyncio.run(test_get_all_avatar_usernames())
    asyncio.run(test_no_leave_if_alias_still_online())
    asyncio.run(test_leave_when_all_avatars_offline())
    asyncio.run(test_no_aliases_user_triggers_immediately())
    asyncio.run(test_alias_queried_resolves_to_canonical_group())
