#!/usr/bin/env python3
"""
Test 6.5: 重启服务后，定时器从 DB 加载，next_trigger 时间保持正确

验证场景：
  A. 未来触发时间 → 原样保留
  B. 已过期 + repeat=True → 推算到下一个未来触发时间
  C. 已过期 + repeat=False → 保持原值（不修改，也不推算）
  D. next_trigger=None → 跳过（不崩溃）
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))


class MockLogger:
    def info(self, msg):    print(f"  [INFO]  {msg}")
    def error(self, msg):   print(f"  [ERROR] {msg}")
    def warning(self, msg): print(f"  [WARN]  {msg}")


async def setup_db():
    from tortoise import Tortoise
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["src.models"]},
    )
    await Tortoise.generate_schemas()


async def teardown_db():
    from tortoise import Tortoise
    await Tortoise.close_connections()


async def run_tests():
    from src.dal.timer_dao import TimerDAO
    from src.managers.timer_manager import TimerManager

    now = datetime.now().replace(microsecond=0)

    # --- 准备测试数据 ---
    future_trigger = now + timedelta(hours=2)
    past_trigger   = now - timedelta(hours=3)

    await TimerDAO.create(
        key="timer_future",
        message="未来触发",
        target_time="23:00",
        repeat=True,
        enabled=True,
        next_trigger=future_trigger,
    )
    await TimerDAO.create(
        key="timer_past_repeat",
        message="过期且重复",
        target_time="08:00",
        repeat=True,
        enabled=True,
        next_trigger=past_trigger,
    )
    await TimerDAO.create(
        key="timer_past_once",
        message="过期且单次",
        target_time="07:00",
        repeat=False,
        enabled=True,
        next_trigger=past_trigger,
    )
    await TimerDAO.create(
        key="timer_no_trigger",
        message="无触发时间",
        target_time="10:00",
        repeat=True,
        enabled=True,
        next_trigger=None,
    )

    # --- 模拟重启：创建 TimerManager 并注入 mock logger ---
    # 重置单例以便测试可重复运行
    TimerManager._instances = {}
    manager = TimerManager.instance()
    manager._logger = MockLogger()

    print("\n=== 模拟服务重启：调用 _load_timers() ===")
    await manager._load_timers()

    timers = manager.get_timers()
    print(f"\n共加载 {len(timers)} 个定时器\n")

    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        if condition:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}" + (f"\n         {detail}" if detail else ""))

    # A. 未来定时器：次数不变
    t = timers.get("timer_future")
    check("场景 A: timer_future 已加载", t is not None)
    if t:
        loaded_nt = datetime.fromisoformat(t["next_trigger"])
        check(
            "场景 A: next_trigger 保持原值（误差 < 1s）",
            abs((loaded_nt - future_trigger).total_seconds()) < 1,
            f"期望={future_trigger}  实际={loaded_nt}",
        )

    # B. 过期 + repeat：next_trigger 应推到未来
    t = timers.get("timer_past_repeat")
    check("场景 B: timer_past_repeat 已加载", t is not None)
    if t:
        loaded_nt = datetime.fromisoformat(t["next_trigger"])
        check(
            "场景 B: next_trigger 推到未来",
            loaded_nt > now,
            f"当前={now}  实际={loaded_nt}",
        )
        # DB 里也应更新
        db_row = await TimerDAO.get_by_key("timer_past_repeat")
        db_nt = db_row.next_trigger
        if db_nt and db_nt.tzinfo is not None:
            db_nt = db_nt.replace(tzinfo=None)
        check(
            "场景 B: DB 中 next_trigger 同步更新到未来",
            db_nt is not None and db_nt > now,
            f"DB next_trigger={db_nt}",
        )

    # C. 过期 + repeat=False：原值保留（单次定时器不推算）
    t = timers.get("timer_past_once")
    check("场景 C: timer_past_once 已加载", t is not None)
    if t:
        loaded_nt = datetime.fromisoformat(t["next_trigger"])
        check(
            "场景 C: next_trigger 保持原过期值（不推算）",
            abs((loaded_nt - past_trigger).total_seconds()) < 1,
            f"期望={past_trigger}  实际={loaded_nt}",
        )

    # D. next_trigger=None：加载不崩溃，字段为空字符串
    t = timers.get("timer_no_trigger")
    check("场景 D: timer_no_trigger 已加载（无崩溃）", t is not None)
    if t:
        check(
            "场景 D: next_trigger 为空字符串",
            t["next_trigger"] == "",
            f"实际={repr(t['next_trigger'])}",
        )

    # 总数验证
    check("总数: 加载了 4 个定时器", len(timers) == 4, f"实际={len(timers)}")

    print(f"\n{'='*40}")
    print(f"结果: {passed} 通过 / {failed} 失败")
    print(f"{'='*40}\n")
    return failed == 0


async def main():
    print("=== Test 6.5: 重启后定时器从 DB 加载 + next_trigger 校验 ===\n")
    await setup_db()
    try:
        ok = await run_tests()
    finally:
        await teardown_db()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
