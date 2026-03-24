from ushareiplay.core.app_controller import AppController
from ushareiplay.core.config_loader import ConfigLoader
from ushareiplay.core.db_manager import DatabaseManager
import asyncio


async def init_db():
    db_manager = DatabaseManager()
    await db_manager.init()


async def close_db():
    db_manager = DatabaseManager()
    await db_manager.close()


async def run_app():
    config = ConfigLoader.load_config()
    await init_db()
    controller = AppController.instance(config)
    return await controller.start_monitoring()


async def main():
    run_count = 0
    while run_count <= 9:
        res = await run_app()
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
    asyncio.run(main())


if __name__ == "__main__":
    run()
