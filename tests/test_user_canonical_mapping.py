import pytest

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO


@pytest.mark.asyncio
async def test_alias_username_resolves_to_canonical_user():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        canonical = await UserDAO.get_or_create("小明")
        canonical.level = 3
        await canonical.save(update_fields=["level"])

        alias_raw = await UserDAO.get_or_create_raw("明明")
        alias_raw.canonical_user_id = canonical.id
        await alias_raw.save(update_fields=["canonical_user_id"])

        resolved = await UserDAO.get_or_create("明明")
        assert resolved.id == canonical.id
        assert resolved.username == "小明"
        assert resolved.level == 3

        resolved2 = await UserDAO.get_or_create("小明")
        assert resolved2.id == canonical.id
    finally:
        await db.close()
