import logging
from src.core.app_controller import AppController
from src.utils.config_loader import ConfigLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    try:
        # 加载配置
        config = ConfigLoader.load_config()
        
        # 初始化控制器
        controller = AppController(config)
        
        # 启动监控
        controller.start_monitoring()
        
    except Exception as e:
        logger.error(f"Application error: {str(e)}")
        raise

if __name__ == "__main__":
    main() 