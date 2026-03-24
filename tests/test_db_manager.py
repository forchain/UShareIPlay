"""
验证 DatabaseManager 使用新的 ushareiplay.models 注册路径能正确初始化。
使用内存 SQLite，不依赖 Appium 或设备。
"""
import pytest
import pytest_asyncio
from tortoise import Tortoise


@pytest.mark.asyncio
async def test_db_manager_init_with_memory_db():
    """DatabaseManager 应能用内存 DB 完成初始化和 schema 生成"""
    from ushareiplay.core.db_manager import DatabaseManager

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    # 验证 Tortoise 已初始化（连接存在）
    assert Tortoise._inited, "Tortoise 应已完成初始化"

    await manager.close()


@pytest.mark.asyncio
async def test_db_models_registered():
    """ushareiplay.models 中的所有模型应能被 Tortoise 识别"""
    from ushareiplay.core.db_manager import DatabaseManager

    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()

    # 获取已注册的模型（Tortoise.apps 支持 __getitem__ 但不是 dict）
    registered_names = set(Tortoise.apps["models"].keys())
    expected_models = {"User", "SeatReservation", "Keyword",
                       "EnterEvent", "ExitEvent", "ReturnEvent", "Timer"}

    assert expected_models.issubset(registered_names), (
        f"以下模型未注册: {expected_models - registered_names}"
    )

    await manager.close()
