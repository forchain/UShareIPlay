import asyncio

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.dal.keyword_dao import KeywordDAO


async def main():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()

    user_a = await UserDAO.get_or_create("A")
    user_b = await UserDAO.get_or_create("B")
    user_c = await UserDAO.get_or_create("C")

    await KeywordDAO.create(
        keyword="k1",
        command=":help",
        creator_id=user_a.id,
        is_public=False,
    )

    # 默认私有：创建者可执行，其他人不可执行
    assert await KeywordDAO.find_accessible_keyword("k1", "A") is not None
    assert await KeywordDAO.find_accessible_keyword("k1", "B") is None

    # 授权：B/C 可执行
    await KeywordDAO.grant_users("k1", [user_b.id, user_c.id])
    assert await KeywordDAO.find_accessible_keyword("k1", "B") is not None
    assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

    # 取消授权：B 不可执行，C 仍可执行
    await KeywordDAO.revoke_users("k1", [user_b.id])
    assert await KeywordDAO.find_accessible_keyword("k1", "B") is None
    assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

    # 别名：A2 绑定到 canonical A 后，应被视为创建者，可执行
    alias_user = await UserDAO.get_or_create_raw("A2")
    alias_user.canonical_user_id = user_a.id
    await alias_user.save(update_fields=["canonical_user_id"])
    assert await KeywordDAO.find_accessible_keyword("k1", "A2") is not None

    await db.close()
    print("test_keyword_acl.py OK")


if __name__ == "__main__":
    asyncio.run(main())

