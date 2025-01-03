from src.core.app_controller import AppController
from src.utils.config_loader import ConfigLoader

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
        print(f"[main]App restarting... {run_count}")
    if run_count > 9:
        print("[main]App error too many times, exit.")
    else:
        print("[main]App stopped by user, exit.")

if __name__ == "__main__":
    main() 