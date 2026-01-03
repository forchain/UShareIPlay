"""
事件管理器 - 基于 page_source 的事件触发系统

通过一次性获取页面源码并解析，替代多次元素查询，解决性能瓶颈问题。
采用基于文件的事件注册机制，与现有命令系统保持一致的架构风格。
"""

import importlib
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from lxml import etree

from ..core.singleton import Singleton
from ..core.element_wrapper import ElementWrapper


class EventManager(Singleton):
    """
    事件管理器 - 管理所有事件相关的逻辑
    单例模式，提供统一的事件管理服务
    """

    def __init__(self):
        # 延迟初始化 handler 和 logger，避免循环依赖
        self._handler = None
        self._logger = None
        self._config = None

        # 事件相关属性
        self.events_path = Path(__file__).parent.parent / 'events'
        self.event_modules: Dict[str, object] = {}  # 缓存已加载的事件模块
        self.element_to_event: Dict[str, str] = {}  # 元素 key -> 事件模块名映射
        self._initialized = False

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

    def initialize(self):
        """初始化事件管理器，加载所有事件模块"""
        if self._initialized:
            return

        self.load_all_events()
        self._initialized = True
        self.logger.info("EventManager initialized")

    def _parse_module_name(self, module_name: str) -> List[str]:
        """
        解析模块名获取关联的元素 key 列表
        
        文件名规则：逗号分隔多个元素 key
        例如：close_button,confirm.py -> ['close_button', 'confirm']
        
        Args:
            module_name: 模块名（不含 .py 后缀）
            
        Returns:
            元素 key 列表
        """
        return [key.strip() for key in module_name.split(',') if key.strip()]

    def _get_event_class_name(self, module_name: str, module=None) -> str:
        """
        获取事件类名
        
        规则：
        1. 如果模块有 __event__ 属性，使用该值
        2. 否则取第一个元素 key，转换为 PascalCase + Event
        
        Args:
            module_name: 模块名
            module: 已加载的模块（可选）
            
        Returns:
            事件类名
        """
        # 检查模块是否有 __event__ 属性
        if module and hasattr(module, '__event__'):
            return module.__event__

        # 取第一个 key
        keys = self._parse_module_name(module_name)
        if not keys:
            return None

        first_key = keys[0]
        # 转换为 PascalCase + Event
        # 例如：message_list -> MessageListEvent
        parts = first_key.split('_')
        class_name = ''.join(part.capitalize() for part in parts) + 'Event'
        return class_name

    def load_event_module(self, module_name: str):
        """
        动态加载事件模块
        
        Args:
            module_name: 模块名（不含 .py 后缀）
            
        Returns:
            加载的模块，失败返回 None
        """
        try:
            if module_name in self.event_modules:
                return self.event_modules[module_name]

            module_path = (self.events_path / f"{module_name}.py").resolve()
            if not module_path.exists():
                self.logger.error(f'Event module path not exists: {module_path}')
                return None

            package_name = f"src.events.{module_name}"
            spec = importlib.util.spec_from_file_location(package_name, module_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[package_name] = module
            spec.loader.exec_module(module)

            if not module:
                self.logger.error(f'Event module {module_name} failed to load')
                return None

            # 获取事件类名
            class_name = self._get_event_class_name(module_name, module)
            if not class_name:
                self.logger.error(f'Cannot determine event class name for {module_name}')
                return None

            # 检查事件类是否存在
            if not hasattr(module, class_name):
                self.logger.error(f'Event class {class_name} not found in {module_name}')
                return None

            # 创建事件实例
            event_class = getattr(module, class_name)
            module.event = event_class(self.handler)

            # 缓存模块
            self.event_modules[module_name] = module

            # 建立元素 key 到模块的映射
            element_keys = self._parse_module_name(module_name)
            for key in element_keys:
                self.element_to_event[key] = module_name

            self.logger.info(f"Loaded event module: {module_name} -> {class_name}, keys: {element_keys}")
            return module

        except Exception as e:
            self.logger.error(f"Error loading event module {module_name}: {traceback.format_exc()}")
            return None

    def load_all_events(self):
        """加载 events 目录下的所有事件模块"""
        try:
            # 确保 events 目录存在
            if not self.events_path.exists():
                self.logger.warning(f"Events directory not found: {self.events_path}")
                return

            # 获取所有 .py 文件
            event_files = [f.stem for f in self.events_path.glob('*.py')
                           if f.is_file() and not f.stem.startswith('__')]

            self.logger.info(f"Found event files: {event_files}")

            # 加载每个事件模块
            for module_name in event_files:
                try:
                    module = self.load_event_module(module_name)
                    if module:
                        self.logger.info(f"Loaded event module: {module_name}")
                    else:
                        self.logger.error(f"Failed to load event module: {module_name}")
                except Exception as e:
                    self.logger.error(f"Error loading event {module_name}: {traceback.format_exc()}")

        except Exception as e:
            self.logger.error(f"Error loading events: {traceback.format_exc()}")

    def _find_element_in_page_source(self, root: etree._Element, element_key: str) -> Optional[etree._Element]:
        """
        在 page_source 中查找元素
        
        支持 ID 和 XPath 两种方式：
        - ID 方式：查找 resource-id 属性匹配的元素
        - XPath 方式：直接执行 XPath 表达式
        
        Args:
            root: page_source 的根元素
            element_key: 配置中的元素 key
            
        Returns:
            找到的 lxml Element，未找到返回 None
        """
        if element_key not in self.config['elements']:
            return None

        element_value = self.config['elements'][element_key]

        try:
            if element_value.startswith('//'):
                # XPath 方式
                results = root.xpath(element_value)
                return results[0] if results else None
            else:
                # ID 方式：查找 resource-id 匹配的元素
                results = root.xpath(f"//*[@resource-id='{element_value}']")
                return results[0] if results else None
        except Exception as e:
            self.logger.debug(f"Error finding element {element_key}: {str(e)}")
            return None

    def process_events(self, page_source: str) -> int:
        """
        处理事件：解析 page_source，检测元素并触发对应事件
        
        Args:
            page_source: 页面源码 XML 字符串
            
        Returns:
            触发的事件数量
        """
        if not self._initialized:
            self.initialize()

        if not page_source:
            return 0

        triggered_count = 0

        try:
            # 解析 page_source
            root = etree.fromstring(page_source.encode('utf-8'))

            # 遍历所有注册的元素 key
            for element_key, module_name in self.element_to_event.items():
                try:
                    # 在 page_source 中查找元素
                    xml_element = self._find_element_in_page_source(root, element_key)

                    if xml_element is not None:
                        # 元素存在，触发事件
                        module = self.event_modules.get(module_name)
                        if module and hasattr(module, 'event'):
                            # 创建元素包装器
                            wrapper = ElementWrapper(xml_element, self.handler, element_key)
                            # 调用事件处理函数
                            module.event.handle(element_key, wrapper)
                            triggered_count += 1
                            self.logger.debug(f"Event triggered for {element_key}")

                except Exception as e:
                    self.logger.error(f"Error processing event for {element_key}: {str(e)}")

        except etree.XMLSyntaxError as e:
            self.logger.error(f"Failed to parse page_source: {str(e)}")
        except Exception as e:
            self.logger.error(f"Error in process_events: {traceback.format_exc()}")

        return triggered_count

    def get_page_source(self) -> Optional[str]:
        """
        获取当前页面的 page_source
        
        Returns:
            页面源码 XML 字符串，失败返回 None
        """
        try:
            return self.handler.driver.page_source
        except Exception as e:
            self.logger.error(f"Failed to get page_source: {str(e)}")
            return None

    def get_event(self, element_key: str):
        """
        根据元素 key 获取对应的事件实例
        
        Args:
            element_key: 元素 key
            
        Returns:
            事件实例或 None
        """
        module_name = self.element_to_event.get(element_key)
        if module_name:
            module = self.event_modules.get(module_name)
            if module and hasattr(module, 'event'):
                return module.event
        return None

    def get_registered_elements(self) -> List[str]:
        """
        获取所有已注册的元素 key 列表
        
        Returns:
            元素 key 列表
        """
        return list(self.element_to_event.keys())

