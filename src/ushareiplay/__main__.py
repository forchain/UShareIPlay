from ushareiplay.core.app_controller import AppController
from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.db_manager import DatabaseManager
from ushareiplay.core.singleton import Singleton
import asyncio
import sys


async def init_db():
    db_manager = DatabaseManager()
    await db_manager.init()


async def close_db():
    db_manager = DatabaseManager()
    await db_manager.close()


async def run_app():
    config = ConfigLoader.load_config()
    await init_db()
    controller = None
    try:
        controller = AppController.initialize(config)
        return await controller.start_monitoring()
    finally:
        if controller is not None:
            await controller.shutdown()
        Singleton.reset_all_instances()


async def main():
    run_count = 0
    while run_count <= 9:
        try:
            res = await run_app()
        except Exception as e:
            run_count += 1
            print(f"[main]App crashed ({e}), restarting... {run_count}")
            continue
        if res:
            break
        run_count += 1
        print(f"[main]App restarting... {run_count}")
    if run_count > 9:
        print("[main]App error too many times, exit.")
    else:
        print("[main]App stopped by user, exit.")

    await close_db()


def run():
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(errors="replace")
        except Exception:
            pass
    asyncio.run(main())


if __name__ == "__main__":
    run()
