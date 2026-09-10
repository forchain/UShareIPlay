import pytest

from ushareiplay.commands.level import LevelCommand
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.models.message_info import MessageInfo


class DummyController:
    def __init__(self, config=None):
        self.config = config or {
            "room_owner": "Joyer",
            "admin_users": ["Outlier", "Chainer"],
            "system_users": ["Timer", "Agent"],
            "soul": {
                "room_owner": "Joyer",
                "admin_users": ["Outlier", "Chainer"],
                "system_users": ["Timer", "Agent"],
            },
        }
        self.soul_handler = None
        self.music_handler = None


@pytest.fixture
async def setup_db():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_level_query_self(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    # 准备用户
    user = await UserDAO.get_or_create("Alice")
    user.level = 2
    await user.save(update_fields=["level"])

    msg = MessageInfo(nickname="Alice", content=":level")
    res = await cmd.process(msg, [])

    assert "message" in res
    assert "您当前等级为 L2" in res["message"]


@pytest.mark.asyncio
async def test_level_query_target_user(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    user = await UserDAO.get_or_create("Bob")
    user.level = 4
    await user.save(update_fields=["level"])

    msg = MessageInfo(nickname="Alice", content=":level Bob")
    res = await cmd.process(msg, ["Bob"])

    assert "message" in res
    assert "用户 Bob 的等级为 L4" in res["message"]


@pytest.mark.asyncio
async def test_level_query_alias_resolves_to_canonical(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    canonical = await UserDAO.get_or_create("Charlie")
    canonical.level = 3
    await canonical.save(update_fields=["level"])

    alias_raw = await UserDAO.get_or_create_raw("Charlie_Alias")
    alias_raw.canonical_user_id = canonical.id
    await alias_raw.save(update_fields=["canonical_user_id"])

    # 查询别名，应展示主账号及其等级
    msg = MessageInfo(nickname="Alice", content=":level Charlie_Alias")
    res = await cmd.process(msg, ["Charlie_Alias"])

    assert "message" in res
    assert "用户 Charlie 的等级为 L3" in res["message"]


@pytest.mark.asyncio
async def test_level_set_by_room_owner_or_admin(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    target = await UserDAO.get_or_create("TargetUser")
    target.level = 1
    await target.save(update_fields=["level"])

    # 房主 Joyer 将其设置为 L9
    msg = MessageInfo(nickname="Joyer", content=":level TargetUser 9")
    res = await cmd.process(msg, ["TargetUser", "9"])

    assert "message" in res
    assert "已将用户 TargetUser 的等级设置为 L9" in res["message"]

    updated = await UserDAO.get_or_create("TargetUser")
    assert updated.level == 9

    # 管理员 Outlier 将其设置为 L8
    msg_admin = MessageInfo(nickname="Outlier", content=":level TargetUser 8")
    res_admin = await cmd.process(msg_admin, ["TargetUser", "8"])
    assert "message" in res_admin
    assert "已将用户 TargetUser 的等级设置为 L8" in res_admin["message"]


@pytest.mark.asyncio
async def test_level_set_by_automated_system_user_rejected(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    target = await UserDAO.get_or_create("TargetUser")
    target.level = 1
    await target.save(update_fields=["level"])

    # 自动化系统角色 Timer 无权随意设置等级
    msg = MessageInfo(nickname="Timer", content=":level TargetUser 9")
    res = await cmd.process(msg, ["TargetUser", "9"])
    assert "error" in res
    assert "权限不足" in res["error"]


@pytest.mark.asyncio
async def test_level_set_by_higher_level_user_success(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    caller = await UserDAO.get_or_create("Leader")
    caller.level = 5
    await caller.save(update_fields=["level"])

    target = await UserDAO.get_or_create("Member")
    target.level = 1
    await target.save(update_fields=["level"])

    # L5 用户将 L1 用户修改为 L3（目标当前 < 5 且 目标新等级 3 < 5）
    msg = MessageInfo(nickname="Leader", content=":level Member 3")
    res = await cmd.process(msg, ["Member", "3"])

    assert "message" in res
    assert "已将用户 Member 的等级设置为 L3" in res["message"]

    updated = await UserDAO.get_or_create("Member")
    assert updated.level == 3


@pytest.mark.asyncio
async def test_level_set_reject_target_equal_or_higher_level(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    caller = await UserDAO.get_or_create("UserA")
    caller.level = 3
    await caller.save(update_fields=["level"])

    target_same = await UserDAO.get_or_create("UserB")
    target_same.level = 3
    await target_same.save(update_fields=["level"])

    target_higher = await UserDAO.get_or_create("UserC")
    target_higher.level = 4
    await target_higher.save(update_fields=["level"])

    # 尝试修改同级用户 -> 拦截
    msg1 = MessageInfo(nickname="UserA", content=":level UserB 1")
    res1 = await cmd.process(msg1, ["UserB", "1"])
    assert "error" in res1
    assert "权限不足" in res1["error"]

    # 尝试修改更高等级用户 -> 拦截
    msg2 = MessageInfo(nickname="UserA", content=":level UserC 1")
    res2 = await cmd.process(msg2, ["UserC", "1"])
    assert "error" in res2
    assert "权限不足" in res2["error"]


@pytest.mark.asyncio
async def test_level_set_reject_new_level_equal_or_higher_than_caller(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    caller = await UserDAO.get_or_create("UserA")
    caller.level = 3
    await caller.save(update_fields=["level"])

    target = await UserDAO.get_or_create("UserB")
    target.level = 1
    await target.save(update_fields=["level"])

    # 目标虽然 < 3，但试图设定为 3 (同级提权) -> 拦截
    msg1 = MessageInfo(nickname="UserA", content=":level UserB 3")
    res1 = await cmd.process(msg1, ["UserB", "3"])
    assert "error" in res1
    assert "权限不足" in res1["error"]

    # 试图设定为 4 (跨级提权) -> 拦截
    msg2 = MessageInfo(nickname="UserA", content=":level UserB 4")
    res2 = await cmd.process(msg2, ["UserB", "4"])
    assert "error" in res2
    assert "权限不足" in res2["error"]


@pytest.mark.asyncio
async def test_level_set_alias_updates_canonical(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    canonical = await UserDAO.get_or_create("RealUser")
    canonical.level = 0
    await canonical.save(update_fields=["level"])

    alias_raw = await UserDAO.get_or_create_raw("AliasUser")
    alias_raw.canonical_user_id = canonical.id
    await alias_raw.save(update_fields=["canonical_user_id"])

    # 房主通过 alias 设置等级
    msg = MessageInfo(nickname="Joyer", content=":level AliasUser 2")
    res = await cmd.process(msg, ["AliasUser", "2"])

    assert "message" in res
    assert "已将用户 RealUser 的等级设置为 L2" in res["message"]

    # 主账号和别名均应为 L2
    resolved_canonical = await UserDAO.get_or_create("RealUser")
    resolved_alias = await UserDAO.get_or_create("AliasUser")
    assert resolved_canonical.level == 2
    assert resolved_alias.level == 2


@pytest.mark.asyncio
async def test_level_invalid_args_and_quotes(setup_db):
    ctl = DummyController()
    cmd = LevelCommand(ctl)

    # 非法数字
    msg = MessageInfo(nickname="Joyer", content=":level TargetUser abc")
    res = await cmd.process(msg, ["TargetUser", "abc"])
    assert "error" in res
    assert "0-9" in res["error"]

    # 超出范围 (如 10)
    msg = MessageInfo(nickname="Joyer", content=":level TargetUser 10")
    res = await cmd.process(msg, ["TargetUser", "10"])
    assert "error" in res
    assert "0-9" in res["error"]

    # 参数过多
    msg = MessageInfo(nickname="Joyer", content=":level TargetUser 1 extra")
    res = await cmd.process(msg, ["TargetUser", "1", "extra"])
    assert "error" in res
    assert "参数过多" in res["error"]

    # 带空格引号昵称
    msg = MessageInfo(nickname="Joyer", content=':level "User With Spaces" 2')
    res = await cmd.process(msg, ['"User With Spaces"', '2'])
    assert "message" in res
    assert "已将用户 User With Spaces 的等级设置为 L2" in res["message"]
