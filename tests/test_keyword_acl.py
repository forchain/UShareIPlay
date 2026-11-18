import pytest

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.keyword_repository import TortoiseKeywordRepository
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository

UserDAO = TortoiseUserRepository()


repository = TortoiseKeywordRepository()


@pytest.mark.asyncio
async def test_private_keyword_acl_and_canonical_alias_access():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        user_a = await UserDAO.get_or_create("A")
        user_b = await UserDAO.get_or_create("B")
        user_c = await UserDAO.get_or_create("C")

        await repository.create(
            keyword="k1",
            command=":help",
            creator_id=user_a.id,
            is_public=False,
        )

        assert await repository.find_accessible_keyword("k1", "A") is not None
        assert await repository.find_accessible_keyword("k1", "B") is None

        await repository.grant_users("k1", [user_b.id, user_c.id])
        assert await repository.find_accessible_keyword("k1", "B") is not None
        assert await repository.find_accessible_keyword("k1", "C") is not None

        await repository.revoke_users("k1", [user_b.id])
        assert await repository.find_accessible_keyword("k1", "B") is None
        assert await repository.find_accessible_keyword("k1", "C") is not None

        alias_user = await UserDAO.get_or_create_raw("A2")
        await UserDAO.set_canonical(alias_user.id, user_a.id)
        assert await repository.find_accessible_keyword("k1", "A2") is not None
    finally:
        await db.close()
