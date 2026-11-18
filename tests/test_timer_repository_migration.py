"""遗留 timers.json 迁移已收进 Tortoise 仓储的启动准备。"""

import json

import pytest
import pytest_asyncio

from ushareiplay.adapters.outbound.persistence.db_manager import DatabaseManager
from ushareiplay.adapters.outbound.persistence.timer_repository import (
    TortoiseTimerRepository,
)


@pytest_asyncio.fixture
async def repository(tmp_path, monkeypatch):
    import ushareiplay.adapters.outbound.persistence.timer_repository as module

    db = DatabaseManager(db_url="sqlite://:memory:")
    await db.init()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "timers.json").write_text(
        json.dumps(
            {
                "morning": {
                    "message": "早安",
                    "target_time": "08:00",
                    "repeat": True,
                    "enabled": True,
                    "next_trigger": "2026-01-02T08:00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    try:
        yield TortoiseTimerRepository()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prepare_migrates_legacy_json_once(repository):
    await repository.prepare()

    migrated = await repository.get_by_key("morning")
    assert migrated.message == "早安"
    assert migrated.repeat is True

    # 第二次启动不会重复迁移，也不会覆盖已有行。
    await repository.prepare()
    assert await repository.count() == 1
