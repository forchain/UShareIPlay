import logging
from src.core.app_controller import AppController
from src.utils.config_loader import ConfigLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def run_app():
    # 加载配置
    config = ConfigLoader.load_config()

    # 初始化控制器
    controller = AppController(config)

    # 启动监控
    return controller.start_monitoring()

def main():
    run_count = 0
    while run_count <= 9:
        res = run_app()
        if res:
            break
        run_count += 1
        logger.error(f"[main]App restarting... {run_count}")
    if run_count > 9:
        logger.error("[main]App error too many times, exit.")
    else:
        logger.info("[main]App stopped by user, exit.")

if __name__ == "__main__":
    main() 