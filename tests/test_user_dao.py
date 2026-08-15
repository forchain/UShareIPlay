import pytest
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.models import User


@pytest.mark.asyncio
async def test_record_owner_gift_upgrades_level_below_4():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        user = await UserDAO.get_or_create("Bob")
        assert user.level == 0

        updated = await UserDAO.record_owner_gift("Bob")
        assert updated.level == 4
        assert updated.heat_value == 0

        # Verify persisted
        db_user = await User.get(id=updated.id)
        assert db_user.level == 4

        # Test from level 3
        user2 = await UserDAO.get_or_create("Charlie")
        user2.level = 3
        await user2.save()
        updated2 = await UserDAO.record_owner_gift("Charlie")
        assert updated2.level == 4
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_owner_gift_does_not_downgrade():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        # Level 4 user
        user4 = await UserDAO.get_or_create("User4")
        user4.level = 4
        await user4.save()
        res4 = await UserDAO.record_owner_gift("User4")
        assert res4.level == 4

        # Level 5 user
        user5 = await UserDAO.get_or_create("User5")
        user5.level = 5
        await user5.save()
        res5 = await UserDAO.record_owner_gift("User5")
        assert res5.level == 5

        # Level 9 user
        user9 = await UserDAO.get_or_create("Owner")
        user9.level = 9
        await user9.save()
        res9 = await UserDAO.record_owner_gift("Owner")
        assert res9.level == 9
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_heat_contribution_base_level_5():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        user = await UserDAO.get_or_create("Dave")
        assert user.level == 0
        assert user.heat_value == 0

        updated = await UserDAO.record_heat_contribution("Dave", 100)
        assert updated.level == 5
        assert updated.heat_value == 100

        # Level 4 user upgrading to 5
        user_l4 = await UserDAO.get_or_create("Eve")
        user_l4.level = 4
        await user_l4.save()
        updated_l4 = await UserDAO.record_heat_contribution("Eve", 500)
        assert updated_l4.level == 5
        assert updated_l4.heat_value == 500

        # Level 6 user not downgrading to 5
        user_l6 = await UserDAO.get_or_create("Frank")
        user_l6.level = 6
        await user_l6.save()
        updated_l6 = await UserDAO.record_heat_contribution("Frank", 500)
        assert updated_l6.level == 6
        assert updated_l6.heat_value == 500
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_record_heat_contribution_cumulative_thresholds():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        # Step 1: 6,000 heat -> Level 5 (not > 10,000 yet)
        user = await UserDAO.record_heat_contribution("Grace", 6000)
        assert user.heat_value == 6000
        assert user.level == 5

        # Step 2: +5,000 heat -> total 11,000 (> 10,000) -> Level 6
        user = await UserDAO.record_heat_contribution("Grace", 5000)
        assert user.heat_value == 11000
        assert user.level == 6

        # Step 3: +90,000 heat -> total 101,000 (> 100,000) -> Level 7
        user = await UserDAO.record_heat_contribution("Grace", 90000)
        assert user.heat_value == 101000
        assert user.level == 7

        # Step 4: +900,000 heat -> total 1,001,000 (> 1,000,000) -> Level 8
        user = await UserDAO.record_heat_contribution("Grace", 900000)
        assert user.heat_value == 1001000
        assert user.level == 8

        # Step 5: Level 9 user contributing 2,000,000 heat -> stays Level 9
        owner = await UserDAO.get_or_create("OwnerUser")
        owner.level = 9
        await owner.save()
        updated_owner = await UserDAO.record_heat_contribution("OwnerUser", 2000000)
        assert updated_owner.heat_value == 2000000
        assert updated_owner.level == 9
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_heat_contribution_with_alias_mapping():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        canonical = await UserDAO.get_or_create("MainAccount")
        alias_raw = await UserDAO.get_or_create_raw("AltAccount")
        alias_raw.canonical_user_id = canonical.id
        await alias_raw.save(update_fields=["canonical_user_id"])

        # AltAccount contributes 6,000 heat
        res1 = await UserDAO.record_heat_contribution("AltAccount", 6000)
        assert res1.id == canonical.id
        assert res1.heat_value == 6000
        assert res1.level == 5

        # MainAccount contributes 5,000 heat -> cumulative 11,000 -> Level 6
        res2 = await UserDAO.record_heat_contribution("MainAccount", 5000)
        assert res2.id == canonical.id
        assert res2.heat_value == 11000
        assert res2.level == 6

        # Fetching via AltAccount reflects canonical values
        resolved = await UserDAO.get_or_create("AltAccount")
        assert resolved.id == canonical.id
        assert resolved.heat_value == 11000
        assert resolved.level == 6
    finally:
        await db.close()
