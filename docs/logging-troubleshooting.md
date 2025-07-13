# 日志配置故障排除指南

## 问题描述
在指定的 logs 目录中只找到了 `chat.log`，没有找到其他日志文件。

## 问题原因
多个组件还在使用 `logging.getLogger()` 直接创建日志器，而没有使用新的 `LoggerConfig` 配置系统。

## 解决方案
已经修改了以下组件，使其使用 `LoggerConfig`：

### 1. 数据访问层 (DAL)
- **SeatReservationDAO**: 添加了 `init_logger()` 方法和 `_get_logger()` 方法
- 在 `AppController` 初始化时调用 `SeatReservationDAO.init_logger(config)`

### 2. 管理器层 (Managers)
- **AdminManager**: 使用 `LoggerConfig` 创建日志器
- **SeatManager**: 添加了类级别的 `_logger_config` 和 `_get_logger()` 方法
- **SeatUIManager**: 使用 `LoggerConfig` 创建日志器

### 3. 应用控制器
- **AppController**: 在初始化时设置所有组件的日志配置

## 修改的文件

### 核心文件
- `src/utils/logger_config.py` - 日志配置工具类
- `src/utils/app_handler.py` - 使用 LoggerConfig
- `src/core/app_controller.py` - 初始化所有日志配置

### 数据访问层
- `src/dal/seat_reservation_dao.py` - 添加日志配置支持

### 管理器层
- `src/managers/admin_manager.py` - 使用 LoggerConfig
- `src/managers/seat_manager/__init__.py` - 添加日志配置支持
- `src/managers/seat_manager/seat_ui.py` - 使用 LoggerConfig

### 消息管理
- `src/soul/message_manager.py` - 使用 LoggerConfig 设置聊天日志

## 验证方法

### 1. 检查日志目录
```bash
ls -la ../logs/
```

应该看到以下文件：
- `chat.log` - 聊天日志
- `AppHandler_YYYY-MM-DD.log` - AppHandler 日志
- `AdminManager_YYYY-MM-DD.log` - 管理员日志
- `SeatManager_YYYY-MM-DD.log` - 座位管理日志
- `SeatUI_YYYY-MM-DD.log` - 座位UI日志
- `seat_dao_YYYY-MM-DD.log` - 座位数据访问日志

### 2. 检查日志内容
```bash
cat ../logs/AppHandler_2025-07-12.log
```

应该看到格式化的日志信息：
```
[INFO]function_name:line_number - Log message
[WARNING]function_name:line_number - Warning message
[ERROR]function_name:line_number - Error message
```

### 3. 配置验证
确保 `config.yaml` 中有正确的日志配置：
```yaml
logging:
  logs_dir: "../logs"  # 日志目录路径
  log_level: "INFO"    # 日志级别
  max_log_size: "10MB" # 文件大小限制
  backup_count: 5      # 备份文件数量
```

## 常见问题

### 1. 日志文件为空
- 检查日志级别设置
- 确保应用正在运行并产生日志
- 检查文件权限

### 2. 日志目录不存在
- 系统会自动创建目录
- 检查父目录权限
- 验证路径配置

### 3. 日志格式不正确
- 检查 LoggerConfig 的格式化设置
- 确保使用正确的日志方法

## 最佳实践

### 1. 日志级别
- **开发环境**: 使用 `DEBUG` 级别
- **生产环境**: 使用 `INFO` 或 `WARNING` 级别

### 2. 日志轮转
- 设置合适的文件大小限制
- 配置适当的备份文件数量
- 定期清理旧日志文件

### 3. 路径配置
- 使用相对路径便于部署
- 使用绝对路径确保固定位置
- 考虑磁盘空间和权限

## 测试脚本
可以使用以下简单的测试来验证日志配置：

```python
from src.utils.config_loader import ConfigLoader
from src.utils.logger_config import LoggerConfig

# 加载配置
config = ConfigLoader.load_config()

# 创建日志配置
logger_config = LoggerConfig(config)

# 测试日志器
logger = logger_config.setup_logger('test_logger')
logger.info("Test message")
logger.warning("Test warning")
logger.error("Test error")
```

运行后检查 `../logs/test_logger_YYYY-MM-DD.log` 文件。 