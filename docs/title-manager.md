# 标题管理器 (TitleManager)

## 概述
标题管理器负责房间标题的存储、管理和UI操作，支持从UI解析现有房间名称进行初始化。

## 功能特性

### 1. 标题管理
- 存储当前标题和下一个标题
- 管理标题更新状态
- 处理标题更新冷却时间

### 2. UI操作
- 封装房间标题的UI更新操作
- 处理编辑、输入、确认等UI交互
- 错误处理和状态验证

### 3. UI解析初始化
- 从UI解析现有房间名称
- 自动分离主题和标题
- 初始化管理器状态

### 4. 主题同步
- UI更新成功后自动同步主题管理器状态
- 确保主题管理器与UI显示一致
- 避免状态不一致问题

## 主要方法

### 初始化方法
```python
def __init__(self, handler, theme_manager=None):
    # handler: UI操作处理器
    # theme_manager: 主题管理器（可选）
```

### 标题获取方法
```python
def get_current_title(self):
    """获取当前标题"""
    
def get_next_title(self):
    """获取下一个标题"""
    
def get_title_to_update(self):
    """获取要更新的标题（优先返回当前标题，其次下一个标题，最后从UI解析）"""
```

### 标题设置方法
```python
def set_next_title(self, title: str):
    """设置下一个标题，包含冷却时间检查"""
    
def update_title_ui(self, title: str, theme: str = None):
    """执行UI更新操作"""
    
def force_update_title(self, title: str, theme: str = None):
    """强制更新标题（绕过冷却时间）"""
```

### 状态检查方法
```python
def can_update_now(self):
    """检查是否可以立即更新（不在冷却期内）"""
```

### UI解析方法
```python
def _parse_title_from_ui(self):
    """从UI解析当前房间标题"""
    
def _initialize_from_ui(self):
    """启动时从UI初始化标题和主题"""
```

## UI解析功能

### 解析逻辑
1. **查找房间标题元素**: 使用 `chat_room_title` 元素ID
2. **获取标题文本**: 从UI元素中提取文本内容
3. **解析格式**: 支持 `主题｜标题` 格式
4. **更新状态**: 自动更新主题管理器和当前标题

### 支持的格式
- `享乐｜经典老歌` → 主题: "享乐", 标题: "经典老歌"
- `音乐｜劲爆舞曲` → 主题: "音乐", 标题: "劲爆舞曲"
- `没有主题的标题` → 主题: 默认, 标题: "没有主题的标题"
- `空标题` → 主题: 默认, 标题: None

### 初始化时机
- 管理器创建时自动初始化
- 仅在当前标题和下一个标题都为空时执行
- 避免覆盖已设置的标题

## 使用示例

### 基本使用
```python
# 创建管理器
handler = SoulHandler(driver, config)
theme_manager = ThemeManager(handler)
title_manager = TitleManager(handler, theme_manager)

# 获取标题
current_title = title_manager.get_current_title()
next_title = title_manager.get_next_title()

# 设置标题
result = title_manager.set_next_title("新标题")

# 检查更新状态
if title_manager.can_update_now():
    title_manager.update_title_ui("新标题", "音乐")
```

### UI解析示例
```python
# 管理器会自动从UI解析现有标题
# 如果房间标题是 "享乐｜经典老歌"
# 解析后：
# - 主题管理器主题: "享乐"
# - 标题管理器当前标题: "经典老歌"
```

## 错误处理

### 常见错误
- **UI元素未找到**: 记录日志，返回None
- **标题文本为空**: 记录日志，返回None
- **解析失败**: 记录错误日志，返回None
- **UI操作失败**: 返回错误信息

### 错误恢复
- 解析失败时保持默认状态
- UI操作失败时不影响标题设置
- 提供详细的错误日志

## 与主题管理器的集成

### 依赖关系
- 标题管理器可以接收主题管理器作为参数
- 解析UI时会自动更新主题管理器
- 更新标题时会使用当前主题

### 数据流
1. UI解析 → 更新主题管理器 → 设置当前标题
2. 标题更新 → 使用主题管理器主题 → 执行UI操作
3. UI更新成功 → 同步主题管理器状态 → 确保状态一致

## 最佳实践

### 1. 初始化
- 在应用启动时创建管理器
- 确保UI元素可用
- 处理初始化失败的情况

### 2. 标题更新
- 使用 `set_next_title` 设置标题
- 使用 `can_update_now` 检查状态
- 使用 `force_update_title` 绕过冷却时间

### 3. 错误处理
- 检查方法返回值
- 处理UI操作失败
- 记录详细的错误信息

### 4. 状态管理
- 避免直接修改内部状态
- 使用公共方法访问状态
- 保持状态一致性
