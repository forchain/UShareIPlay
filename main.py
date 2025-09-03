from src.core.app_controller import AppController
from src.core.config_loader import ConfigLoader
from src.core.db_manager import DatabaseManager
import asyncio

async def init_db():
    db_manager = DatabaseManager()
    await db_manager.init()

async def close_db():
    db_manager = DatabaseManager()
    await db_manager.close()

async def run_app():
    # 加载配置
    config = ConfigLoader.load_config()

    # Initialize database
    await init_db()

    # 初始化控制器 using singleton pattern
    controller = AppController.instance(config)

    # 启动监控
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
        
    # Close database connection
    await close_db()

if __name__ == "__main__":
    asyncio.run(main()) 