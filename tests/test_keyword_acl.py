import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.keyword_dao import KeywordDAO
from ushareiplay.dal.user_dao import UserDAO


@pytest.mark.asyncio
async def test_private_keyword_acl_and_canonical_alias_access():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        user_a = await UserDAO.get_or_create("A")
        user_b = await UserDAO.get_or_create("B")
        user_c = await UserDAO.get_or_create("C")

        await KeywordDAO.create(
            keyword="k1",
            command=":help",
            creator_id=user_a.id,
            is_public=False,
        )

        assert await KeywordDAO.find_accessible_keyword("k1", "A") is not None
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is None

        await KeywordDAO.grant_users("k1", [user_b.id, user_c.id])
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is not None
        assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

        await KeywordDAO.revoke_users("k1", [user_b.id])
        assert await KeywordDAO.find_accessible_keyword("k1", "B") is None
        assert await KeywordDAO.find_accessible_keyword("k1", "C") is not None

        alias_user = await UserDAO.get_or_create_raw("A2")
        alias_user.canonical_user_id = user_a.id
        await alias_user.save(update_fields=["canonical_user_id"])
        assert await KeywordDAO.find_accessible_keyword("k1", "A2") is not None
    finally:
        await db.close()
