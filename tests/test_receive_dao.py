import pytest
import pytest_asyncio
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.dal.receive_dao import ReceiveDao


@pytest_asyncio.fixture
async def db_init():
    manager = DatabaseManager(db_url="sqlite://:memory:")
    await manager.init()
    yield
    await manager.close()


@pytest.mark.asyncio
async def test_receive_dao_crud(db_init):
    event = await ReceiveDao.create("Alice", ":play song")
    assert event.id is not None
    assert event.command == ":play song"

    items = await ReceiveDao.get_by_username("Alice")
    assert len(items) == 1
    assert items[0].command == ":play song"

    fetched = await ReceiveDao.get_by_id(event.id)
    assert fetched is not None
    assert fetched.id == event.id

    deleted = await ReceiveDao.delete_by_id(event.id)
    assert deleted is True

    items = await ReceiveDao.get_by_username("Alice")
    assert len(items) == 0


@pytest.mark.asyncio
async def test_receive_dao_delete_all(db_init):
    await ReceiveDao.create("Bob", ":say hello")
    await ReceiveDao.create("Bob", ":say world")
    count = await ReceiveDao.delete_all_by_username("Bob")
    assert count == 2
    items = await ReceiveDao.get_by_username("Bob")
    assert len(items) == 0
