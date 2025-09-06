# Command Architecture Principles

## 设计原则

### 1. 命令封闭性 (Command Encapsulation)

命令应该保持封闭性，避免直接依赖其他命令。每个命令只负责：
- 解析自己的参数
- 执行自己的专有逻辑
- 通过 Manager 调用公共服务

**❌ 错误做法：**
```python
# 命令直接调用其他命令
self.controller.title_command.change_title("新标题")
self.controller.play_command.play_song("歌曲名")
```

**✅ 正确做法：**
```python
# 通过 Manager 调用公共服务（无需传递参数）
from ..managers.content_manager import ContentManager
from ..managers.music_manager import MusicManager

content_manager = ContentManager.instance()
music_manager = MusicManager.instance()

content_manager.change_title("新标题")
music_manager.play_song("歌曲名")
```

### 2. Manager 单例模式

所有 Manager 都应该使用单例模式，并通过内部引用单例 Handler，确保：
- 资源的统一管理
- 状态的一致性
- 避免重复初始化
- 消除依赖注入的复杂性

**Manager 实现模板：**
```python
from ..core.singleton import Singleton

class YourManager(Singleton):
    def __init__(self):
        # 获取所需的 Handler 单例实例
        from ..soul.soul_handler import SoulHandler
        # 或者 from ..music.qq_music_handler import QQMusicHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger
    
    def your_method(self, param):
        # 实现具体逻辑
        pass
```

### 3. 职责分离

#### Command 职责：
- 参数解析和验证
- 简单的命令专有逻辑
- 调用 Manager 执行复杂操作
- 返回格式化的结果

#### Manager 职责：
- 复杂的业务逻辑
- 可能被多个命令使用的公共服务
- UI 交互和状态管理
- 错误处理和日志记录

### 4. 单例 Handler 引用

Manager 通过内部引用获取所需的单例 Handler：
- 所有 Handler 都是单例（SoulHandler, QQMusicHandler）
- Manager 在构造函数中直接获取 Handler 单例实例
- 消除了依赖注入的参数传递复杂性
- 确保所有 Manager 使用相同的 Handler 实例

## 现有 Manager 列表

### ContentManager
负责房间内容管理：
- `change_title(title)` - 修改房间标题
- `change_topic(topic)` - 修改房间话题

### MicManager
负责麦克风管理：
- `toggle_mic(enable)` - 开关麦克风
- `get_mic_status()` - 获取麦克风状态

### MusicManager
负责音乐播放管理：
- `play_song(query)` - 播放指定歌曲
- `pause_resume(should_pause)` - 暂停/恢复播放
- `skip_song()` - 跳过当前歌曲
- `get_current_song_info()` - 获取当前歌曲信息

### SeatManager
负责座位管理：
- 座位预订和检查
- 用户入座管理

### RecoveryManager
负责异常恢复：
- 异常状态检测
- 自动恢复操作

### TimerManager
负责定时任务：
- 定时器管理
- 定时消息发送

### ThemeManager
负责主题管理：
- 房间主题切换

### TitleManager
负责标题管理：
- 标题逻辑处理

## 重构检查清单

在添加新功能或修改现有代码时，请检查：

1. ✅ 命令是否直接调用其他命令？
2. ✅ 复杂逻辑是否提取到 Manager 中？
3. ✅ Manager 是否使用单例模式？
4. ✅ 职责是否清晰分离？
5. ✅ 是否遵循依赖注入原则？

## 示例重构

### 重构前：
```python
class PlayCommand(BaseCommand):
    async def process(self, message_info, parameters):
        # 播放音乐
        result = self.music_handler.play_song(song)
        
        # 直接调用其他命令 ❌
        self.controller.title_command.change_title("新标题")
        self.controller.topic_command.change_topic("新话题")
        
        return result
```

### 重构后：
```python
class PlayCommand(BaseCommand):
    async def process(self, message_info, parameters):
        # 使用 music_manager 播放音乐
        from ..managers.music_manager import MusicManager
        music_manager = MusicManager.instance(self.music_handler)
        result = music_manager.play_song(song)
        
        # 使用 content_manager 管理内容 ✅
        from ..managers.content_manager import ContentManager
        content_manager = ContentManager.instance(self.soul_handler)
        content_manager.change_title("新标题")
        content_manager.change_topic("新话题")
        
        return result
```

## 最佳实践

1. **新增功能时**：先考虑是否需要创建新的 Manager
2. **修改现有代码时**：检查是否违反了封闭性原则
3. **代码审查时**：确保遵循上述设计原则
4. **测试时**：Manager 的单例特性使得测试更容易

这些原则确保了代码的可维护性、可扩展性和测试性。
