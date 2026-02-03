import traceback
import yaml
from pathlib import Path
from typing import Optional
from ..core.singleton import Singleton
from ..dal import KeywordDAO, UserDAO
from ..models.keyword import Keyword


class KeywordManager(Singleton):
    """
    关键字管理器 - 管理关键字的增删改查和执行
    单例模式，提供统一的关键字管理服务
    """
    
    def __init__(self):
        # 延迟初始化 handler 和 logger，避免循环依赖
        self._handler = None
        self._logger = None
        self._config = None
        self._default_keyword_command = None

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    @property
    def config(self):
        """延迟获取配置"""
        if self._config is None:
            self._config = self.handler.config
        return self._config

    async def load_keywords_from_config(self):
        """从配置文件加载关键字到数据库
        
        1. 清除所有配置关键字（creator_id is None）
        2. 重新导入配置文件中的关键字
        """
        try:
            # 清除配置关键字（creator_id is None）
            deleted_count = await KeywordDAO.delete_config_keywords()
            self.logger.info(f"Cleared {deleted_count} config keywords")
            
            # 加载关键字配置文件
            config_path = Path('config/keywords.yaml')
            if not config_path.exists():
                self.logger.warning(f"Keywords config file not found: {config_path}")
                return
            
            with open(config_path, 'r', encoding='utf-8') as f:
                keywords_config = yaml.safe_load(f)
            
            # 加载默认关键字
            if 'default_keyword' in keywords_config:
                self._default_keyword_command = keywords_config['default_keyword'].get('command', ':help')
                self.logger.info(f"Loaded default keyword command: {self._default_keyword_command}")
            
            # 加载预设关键字
            if 'keywords' not in keywords_config:
                self.logger.info("No keywords configured")
                return
            
            loaded_count = 0
            for kw_config in keywords_config['keywords']:
                keyword_text = kw_config.get('keyword', '')
                command = kw_config.get('command', '')
                is_public = kw_config.get('is_public', True)
                
                if not keyword_text or not command:
                    continue
                
                # 处理同义词（用 | 分隔）
                keywords = [k.strip() for k in keyword_text.split('|') if k.strip()]
                
                for kw in keywords:
                    await KeywordDAO.create(
                        keyword=kw,
                        command=command,
                        creator_id=None,  # 配置关键字 creator_id 为 None
                        is_public=is_public
                    )
                    loaded_count += 1
                    self.logger.info(f"Loaded config keyword: {kw}")
            
            self.logger.info(f"Loaded {loaded_count} keywords from config")
            print(f"关键字系统初始化完成：加载了 {loaded_count} 个关键字")
            
        except Exception as e:
            error_msg = f"Error loading keywords from config: {traceback.format_exc()}"
            self.logger.error(error_msg)
            print(f"关键字加载失败: {str(e)}")
            traceback.print_exc()

    async def find_keyword(self, keyword: str, username: str) -> Optional[Keyword]:
        """查找匹配的关键字
        
        Args:
            keyword: 关键字文本
            username: 触发用户名
            
        Returns:
            找到的关键字记录，如果没找到或无权限执行则返回 None
        """
        try:
            kw = await KeywordDAO.find_accessible_keyword(keyword, username)
            return kw
        except Exception:
            self.logger.error(f"Error finding keyword: {traceback.format_exc()}")
            return None

    async def add_keyword(self, username: str, keywords: str, command: str, 
                         is_public: bool) -> dict:
        """添加关键字
        
        Args:
            username: 创建者用户名
            keywords: 关键字（支持 | 分隔同义词）
            command: 命令字符串
            is_public: 是否公开
            
        Returns:
            结果字典
        """
        try:
            # 检查用户是否在线
            from ..managers.info_manager import InfoManager
            info_manager = InfoManager.instance()
            if not info_manager.is_user_online(username):
                return {'error': '只有在线用户才能添加关键字'}
            
            # 获取或创建用户
            user = await UserDAO.get_or_create(username)
            
            # 处理同义词
            keyword_list = [k.strip() for k in keywords.split('|') if k.strip()]
            if not keyword_list:
                return {'error': '关键字不能为空'}
            
            added_keywords = []
            覆盖_keywords = []
            failed_keywords = []
            
            for kw in keyword_list:
                # 检查关键字是否已存在
                existing = await KeywordDAO.get_by_keyword(kw)
                
                if existing:
                    # 检查覆盖权限（creator_id is None 表示配置关键字）
                    if existing.creator_id is None:
                        failed_keywords.append(f"{kw}(配置关键字不可覆盖)")
                        continue
                    
                    if existing.creator:
                        if existing.creator.level > user.level:
                            failed_keywords.append(
                                f"{kw}(已被更高等级用户 {existing.creator.username} 创建)"
                            )
                            continue
                    
                    # 可以覆盖，删除旧记录
                    await KeywordDAO.delete_by_keyword(kw)
                    覆盖_keywords.append(kw)
                
                # 创建新关键字
                await KeywordDAO.create(
                    keyword=kw,
                    command=command,
                    creator_id=user.id,
                    is_public=is_public
                )
                added_keywords.append(kw)
            
            # 构建返回消息
            messages = []
            if added_keywords:
                visibility = "公开" if is_public else "私有"
                messages.append(f"成功添加{visibility}关键字: {', '.join(added_keywords)}")
            if 覆盖_keywords:
                messages.append(f"覆盖了关键字: {', '.join(覆盖_keywords)}")
            if failed_keywords:
                messages.append(f"添加失败: {', '.join(failed_keywords)}")
            
            if not messages:
                return {'error': '没有关键字被添加'}
            
            return {'message': '\n'.join(messages)}
            
        except Exception:
            self.logger.error(f"Error adding keyword: {traceback.format_exc()}")
            return {'error': '添加关键字失败'}

    async def update_keyword_publicity(self, username: str, keyword: str, 
                                      is_public: Optional[bool]) -> dict:
        """更新关键字公开性
        
        Args:
            username: 用户名
            keyword: 关键字
            is_public: 公开性（None=切换，True=公开，False=私有）
            
        Returns:
            结果字典
        """
        try:
            # 查找关键字
            kw = await KeywordDAO.get_by_keyword(keyword)
            if not kw:
                return {'error': f'关键字 "{keyword}" 不存在'}
            
            # 检查权限（creator_id is None 表示配置关键字）
            if kw.creator_id is None:
                return {'error': '不能修改配置关键字'}
            
            if not kw.creator or kw.creator.username != username:
                return {'error': '只能修改自己创建的关键字'}
            
            # 切换或设置公开性
            if is_public is None:
                new_is_public = not kw.is_public
            else:
                new_is_public = is_public
            
            await KeywordDAO.update_publicity(keyword, new_is_public)
            
            status = "公开" if new_is_public else "私有"
            return {'message': f'关键字 "{keyword}" 已设置为{status}'}
            
        except Exception:
            self.logger.error(f"Error updating keyword publicity: {traceback.format_exc()}")
            return {'error': '更新关键字公开性失败'}

    async def delete_keyword(self, username: str, keyword: str) -> dict:
        """删除关键字
        
        Args:
            username: 用户名
            keyword: 关键字
            
        Returns:
            结果字典
        """
        try:
            # 查找关键字
            kw = await KeywordDAO.get_by_keyword(keyword)
            if not kw:
                return {'error': f'关键字 "{keyword}" 不存在'}
            
            # 检查权限（creator_id is None 表示配置关键字）
            if kw.creator_id is None:
                return {'error': '不能删除配置关键字'}
            
            if not kw.creator or kw.creator.username != username:
                return {'error': '只能删除自己创建的关键字'}
            
            # 删除关键字
            await KeywordDAO.delete_by_keyword(keyword)
            return {'message': f'成功删除关键字 "{keyword}"'}
            
        except Exception:
            self.logger.error(f"Error deleting keyword: {traceback.format_exc()}")
            return {'error': '删除关键字失败'}

    async def execute_keyword(self, keyword_record: Keyword, username: str, params: str = ""):
        """执行关键字
        
        Args:
            keyword_record: 关键字记录
            username: 触发用户名
            params: 关键词后的参数字符串（空格后的整段），command 中可用 {params} 引用
        """
        try:
            # 替换占位符：{user_name} 用户名，{params} 关键词后的参数
            command = (
                keyword_record.command.replace('{user_name}', username).replace('{params}', params or "")
            )
            
            # 将命令放入消息队列
            from ..core.message_queue import MessageQueue
            from ..models.message_info import MessageInfo
            
            message_queue = MessageQueue.instance()
            message_info = MessageInfo(
                content=command,  # 保留完整格式（包括冒号和分号）
                nickname=username
            )
            
            await message_queue.put_message(message_info)
            self.logger.info(f"Keyword '{keyword_record.keyword}' executed by {username}")
            
        except Exception:
            self.logger.error(f"Error executing keyword: {traceback.format_exc()}")

    async def execute_default_keyword(self, username: str, params: str = ""):
        """执行默认关键字
        
        Args:
            username: 触发用户名
            params: 关键词后的参数字符串，command 中可用 {params} 引用
        """
        try:
            if not self._default_keyword_command:
                self.logger.warning("No default keyword command configured")
                return
            
            # 替换占位符：{user_name} 用户名，{params} 参数
            command = (
                self._default_keyword_command.replace('{user_name}', username).replace('{params}', params or "")
            )
            
            # 将命令放入消息队列
            from ..core.message_queue import MessageQueue
            from ..models.message_info import MessageInfo
            
            message_queue = MessageQueue.instance()
            message_info = MessageInfo(
                content=command,
                nickname=username
            )
            
            await message_queue.put_message(message_info)
            self.logger.info(f"Default keyword executed by {username}")
            
        except Exception:
            self.logger.error(f"Error executing default keyword: {traceback.format_exc()}")
