# 日志配置说明

## 概述
现在可以通过 `config.yaml` 文件来配置日志目录路径和其他日志相关设置，不再需要硬编码的 `logs` 目录。

## 配置选项

在 `config.yaml` 文件中添加以下配置：

```yaml
logging:
  logs_dir: "logs"  # 日志目录路径，可以是相对路径或绝对路径
  log_level: "INFO"  # 日志级别: DEBUG, INFO, WARNING, ERROR
  max_log_size: "10MB"  # 单个日志文件最大大小
  backup_count: 5  # 保留的日志文件数量
```

### 配置参数说明

1. **logs_dir**: 日志目录路径
   - 相对路径：相对于项目根目录（如 "logs", "custom_logs"）
   - 绝对路径：完整的系统路径（如 "/var/log/myapp", "C:\\logs\\myapp"）

2. **log_level**: 日志级别
   - DEBUG: 最详细的日志信息
   - INFO: 一般信息（默认）
   - WARNING: 警告信息
   - ERROR: 错误信息

3. **max_log_size**: 单个日志文件最大大小
   - 支持单位：KB, MB, GB
   - 示例：10MB, 100KB, 1GB

4. **backup_count**: 保留的备份文件数量
   - 当日志文件达到最大大小时，会自动创建备份
   - 超过指定数量的旧备份文件会被自动删除

## 使用示例

### 1. 使用相对路径
```yaml
logging:
  logs_dir: "logs"
  log_level: "INFO"
  max_log_size: "10MB"
  backup_count: 5
```

### 2. 使用绝对路径
```yaml
logging:
  logs_dir: "/var/log/ushareiplay"
  log_level: "DEBUG"
  max_log_size: "50MB"
  backup_count: 10
```

### 3. 使用子目录
```yaml
logging:
  logs_dir: "data/logs"
  log_level: "WARNING"
  max_log_size: "5MB"
  backup_count: 3
```

## 日志文件命名

- **AppHandler 日志**: `AppHandler_YYYY-MM-DD.log`
- **聊天日志**: `chat.log`
- **其他组件日志**: `{组件名}_{YYYY-MM-DD}.log`

## 日志轮转

当日志文件达到配置的最大大小时，系统会自动：
1. 将当前日志文件重命名为 `{原文件名}.1`
2. 创建新的日志文件
3. 删除超过 `backup_count` 数量的旧备份文件

例如：
- `AppHandler_2024-01-15.log` (当前)
- `AppHandler_2024-01-15.log.1` (备份1)
- `AppHandler_2024-01-15.log.2` (备份2)
- ...

## 迁移说明

### 从旧版本升级
1. 现有的 `logs` 目录仍然可以使用
2. 新的配置会自动创建指定的日志目录
3. 旧的日志文件不会被删除

### 配置优先级
1. 如果配置文件中没有 `logging` 部分，使用默认值
2. 默认值：
   - logs_dir: "logs"
   - log_level: "INFO"
   - max_log_size: "10MB"
   - backup_count: 5

## 故障排除

### 1. 权限问题
如果使用绝对路径，确保应用有写入权限：
```bash
# 创建目录并设置权限
sudo mkdir -p /var/log/ushareiplay
sudo chown $USER:$USER /var/log/ushareiplay
```

### 2. 路径不存在
系统会自动创建不存在的目录，但父目录必须存在且有写入权限。

### 3. 磁盘空间
定期检查日志目录的磁盘使用情况：
```bash
du -sh /path/to/logs
```

## 最佳实践

1. **生产环境**：使用绝对路径，设置适当的日志级别
2. **开发环境**：使用相对路径，设置 DEBUG 级别
3. **日志轮转**：根据磁盘空间设置合适的文件大小和备份数量
4. **监控**：定期检查日志文件大小和数量 