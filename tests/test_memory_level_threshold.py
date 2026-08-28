import pytest
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.user_dao import UserDAO
from ushareiplay.dal.user_chat_log_dao import UserChatLogDAO
from ushareiplay.dal.user_memory_dao import UserMemoryDAO
from ushareiplay.managers.memory_manager import MemoryManager


@pytest.mark.asyncio
async def test_memory_context_filters_long_term_for_low_level_user():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        # Default threshold: 20
        mm.configure({"llm": {"memory": {"enabled": True, "min_level_for_long_term": 20}}})

        user = await UserDAO.get_or_create("low_level_user")
        user.level = 5
        await user.save()
        await UserMemoryDAO.update_memory(
            user_id=user.id,
            directives=["称谓: 小五哥"],
            profile_summary="喜欢二次元歌曲",
        )
        await UserChatLogDAO.create("low_level_user", "放首千本樱")

        # Level 5 (< 20): only short-term memory loaded
        ctx = await mm.get_user_dialogue_context("low_level_user", user_level=5)
        assert ctx["directives"] == []
        assert ctx["profile"] == ""
        assert ctx["short_term_chats"] == ["放首千本樱"]

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_context_loads_long_term_for_high_level_user():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        mm.configure({"llm": {"memory": {"enabled": True, "min_level_for_long_term": 20}}})

        user = await UserDAO.get_or_create("vip_user")
        user.level = 25
        await user.save()
        await UserMemoryDAO.update_memory(
            user_id=user.id,
            directives=["称谓: 浩哥", "硬性偏好: 喜好周杰伦"],
            profile_summary="资深房管，偏好华语流行",
        )
        await UserChatLogDAO.create("vip_user", "来首晴天")

        # Level 25 (>= 20): both long-term and short-term memory loaded
        ctx = await mm.get_user_dialogue_context("vip_user", user_level=25)
        assert ctx["directives"] == ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"]
        assert ctx["profile"] == "资深房管，偏好华语流行"
        assert ctx["short_term_chats"] == ["来首晴天"]

    finally:
        await db.close()


@pytest.mark.asyncio
async def test_memory_context_custom_threshold():
    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    try:
        if not MemoryManager.is_initialized():
            MemoryManager.initialize()
        mm = MemoryManager.instance()
        # Custom threshold: 0 (everyone gets long-term memory)
        mm.configure({"llm": {"memory": {"enabled": True, "min_level_for_long_term": 0}}})

        user = await UserDAO.get_or_create("guest_user")
        user.level = 0
        await user.save()
        await UserMemoryDAO.update_memory(
            user_id=user.id,
            directives=["称谓: 新朋友"],
            profile_summary="新访客",
        )
        await UserChatLogDAO.create("guest_user", "你好")

        ctx = await mm.get_user_dialogue_context("guest_user", user_level=0)
        assert ctx["directives"] == ["称谓: 新朋友"]
        assert ctx["profile"] == "新访客"
        assert ctx["short_term_chats"] == ["你好"]


    finally:
        await db.close()
