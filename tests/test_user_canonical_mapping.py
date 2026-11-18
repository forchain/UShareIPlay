import pytest

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.user_repository import TortoiseUserRepository

UserDAO = TortoiseUserRepository()


@pytest.mark.asyncio
async def test_alias_username_resolves_to_canonical_user():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        canonical = await UserDAO.get_or_create("小明")
        await UserDAO.update_level(canonical.id, 3)

        alias_raw = await UserDAO.get_or_create_raw("明明")
        await UserDAO.set_canonical(alias_raw.id, canonical.id)

        resolved = await UserDAO.get_or_create("明明")
        assert resolved.id == canonical.id
        assert resolved.username.value == "小明"
        assert resolved.level == 3

        resolved2 = await UserDAO.get_or_create("小明")
        assert resolved2.id == canonical.id
    finally:
        await db.close()
