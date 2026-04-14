import asyncio

from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO


async def main() -> None:
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()

    canonical = await UserDAO.get_or_create("小明")
    canonical.level = 3
    await canonical.save(update_fields=["level"])

    alias_raw = await UserDAO.get_or_create_raw("明明")
    alias_raw.canonical_user_id = canonical.id
    await alias_raw.save(update_fields=["canonical_user_id"])

    resolved = await UserDAO.get_or_create("明明")
    assert resolved.id == canonical.id, (resolved.id, canonical.id)
    assert resolved.username == "小明"
    assert resolved.level == 3

    # Ensure canonical resolves to itself
    resolved2 = await UserDAO.get_or_create("小明")
    assert resolved2.id == canonical.id

    print("OK: alias username resolves to canonical user")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

