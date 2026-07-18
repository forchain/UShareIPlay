"""
事件管理器 - 基于 page_source 的事件触发系统

通过一次性获取页面源码并解析，替代多次元素查询，解决性能瓶颈问题。
采用基于文件的事件注册机制，与现有命令系统保持一致的架构风格。
"""

import importlib
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lxml import etree

from ushareiplay.core.driver_decorator import with_driver_recovery
from ushareiplay.core.singleton import Singleton
from ushareiplay.core.element_wrapper import ElementWrapper
import asyncio


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
        self._consecutive_unknown_pages = 0
        self._runtime = None

    # 在 _process_events_once 中优先匹配（先于兜底 press_back 相关逻辑）
    _PRIORITY_EVENT_KEYS: Tuple[str, ...] = (
        "accidental_touch_locker",
        "party_name_violation_later",
        # 发帖退出底部菜单与 left_top_close 同时存在时须先点「不保存」，否则会反复点关闭
        "post_draft_dont_save",
    )

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
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

    @property
    def driver_recovery_context(self):
        return getattr(self.handler, "driver_recovery_context", None)

    def configure_runtime(self, runtime):
        self._runtime = runtime

    @property
    def runtime(self):
        if self._runtime is None:
            raise RuntimeError("EventManager runtime has not been configured")
        return self._runtime

    def initialize_events(self):
        """初始化事件管理器，加载所有事件模块"""
        if self._initialized:
            return

        self.load_all_events()
        self._initialized = True

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

            package_name = f"ushareiplay.events.{module_name}"
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
            module.event = event_class(self.handler, runtime=self.runtime)

            # 缓存模块
            self.event_modules[module_name] = module

            # 建立元素 key 到模块的映射
            # 优先使用 __elements__ 字段，如果不存在则从文件名解析
            if hasattr(module, '__elements__') and isinstance(module.__elements__, list):
                element_keys = module.__elements__
            else:
                element_keys = self._parse_module_name(module_name)

            for key in element_keys:
                self.element_to_event[key] = module_name

            return module

        except Exception:
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

            # 加载每个事件模块
            for module_name in event_files:
                try:
                    module = self.load_event_module(module_name)
                    if not module:
                        self.logger.error(f"Failed to load event module: {module_name}")
                except Exception:
                    self.logger.error(f"Error loading event {module_name}: {traceback.format_exc()}")

        except Exception:
            self.logger.error(f"Error loading events: {traceback.format_exc()}")

    def _soul_package_name(self) -> str:
        return (self.config.get("package_name") or "").strip() or "cn.soulapp.android"

    def _root_config(self) -> dict:
        controller = getattr(self.handler, "controller", None)
        root_config = getattr(controller, "config", None)
        if isinstance(root_config, dict):
            return root_config
        return self.config if isinstance(self.config, dict) else {}

    def _qq_music_package_name(self) -> str:
        root_config = self._root_config()
        return (
            ((root_config.get("qq_music") or {}).get("package_name"))
            or "com.tencent.qqmusic"
        )

    def _screen_elements(self) -> dict:
        config = self.config if isinstance(self.config, dict) else {}
        if isinstance(config.get("elements"), dict):
            return config["elements"]

        root_config = self._root_config()
        soul_config = root_config.get("soul") or {}
        elements = soul_config.get("elements")
        return elements if isinstance(elements, dict) else {}

    def _launcher_packages(self) -> List[str]:
        defaults = [
            "com.sec.android.app.launcher",
            "com.android.launcher",
            "com.google.android.apps.nexuslauncher",
        ]
        extra = self.config.get("launcher_packages") or []
        if not isinstance(extra, list):
            return defaults
        merged: List[str] = []
        seen = set()
        for p in extra + defaults:
            if not p or p in seen:
                continue
            seen.add(p)
            merged.append(p)
        return merged

    def _packages_from_parsed_root(self, root: etree._Element) -> Set[str]:
        return {el.get("package") for el in root.iter() if el.get("package")}

    def _packages_from_page_source(self, page_source: str) -> Optional[Set[str]]:
        try:
            root = etree.fromstring(page_source.encode("utf-8"))
        except etree.XMLSyntaxError:
            return None
        return self._packages_from_parsed_root(root)

    def _selector_present(self, root: etree._Element, page_source: str, selector: str) -> bool:
        if not selector or not isinstance(selector, str):
            return False
        if selector in page_source:
            return True
        if selector.startswith("//"):
            try:
                return bool(root.xpath(selector))
            except Exception:
                match = re.search(r'@resource-id\s*=\s*"([^"]+)"', selector)
                if match and match.group(1):
                    return match.group(1) in page_source
            return False
        return bool(root.xpath(f"//*[@resource-id='{selector}']"))

    def describe_screen(self, page_source: str) -> dict:
        screen = {
            "foreground_app": "Unknown",
            "soul_ui_state": "Unknown",
            "qqmusic_ui_state": "Unknown",
            "anchors": [],
        }
        if not page_source:
            return screen

        try:
            root = etree.fromstring(page_source.encode("utf-8"))
        except etree.XMLSyntaxError:
            return screen

        packages = self._packages_from_parsed_root(root)
        soul_pkg = self._soul_package_name()
        qq_pkg = self._qq_music_package_name()
        launchers = set(self._launcher_packages())

        if soul_pkg in packages:
            screen["foreground_app"] = "Soul"
        elif qq_pkg in packages:
            screen["foreground_app"] = "QQMusic"
        elif packages & launchers:
            screen["foreground_app"] = "Launcher"

        anchors = []
        for key in ("message_content", "input_box_entry", "input_box"):
            selector = self._screen_elements().get(key)
            if selector and self._selector_present(root, page_source, selector):
                anchors.append(key)
        screen["anchors"] = anchors

        if screen["foreground_app"] == "Soul":
            screen["soul_ui_state"] = "InChatReady" if "message_content" in anchors else "InUnknownPage"

        return screen

    def _find_element_in_page_source(self, root: etree._Element, element_key: str, module=None) -> Optional[
        etree._Element]:
        """
        在 page_source 中查找元素
        
        支持 ID 和 XPath 两种方式：
        - ID 方式：查找 resource-id 属性匹配的元素
        - XPath 方式：直接执行 XPath 表达式
        
        Args:
            root: page_source 的根元素
            element_key: 配置中的元素 key
            module: 事件模块（可选），用于检查 __multiple__ 属性
            
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
            else:
                # ID 方式：查找 resource-id 匹配的元素
                results = root.xpath(f"//*[@resource-id='{element_value}']")

            # 检查模块是否有 __multiple__ 属性
            if module and hasattr(module, '__multiple__') and module.__multiple__:
                # 返回所有匹配的元素（作为列表的第一个元素，实际是列表）
                return results if results else None
            else:
                # 返回第一个元素（默认行为）
                return results[0] if results else None
        except Exception as e:
            self.logger.debug(f"Error finding element {element_key}: {str(e)}")
            return None

    async def react_to_page(self, page_source: str) -> dict:
        """
        处理事件：解析 page_source，检测元素并触发对应事件
        
        Args:
            page_source: 页面源码 XML 字符串
            
        Returns:
            事件触发数量和未知页面恢复结果
        """
        if not self._initialized:
            self.initialize_events()

        if not page_source:
            return {
                "triggered_count": 0,
                "recovery": {
                    "attempted": False,
                    "suppressed": "no_page_source",
                    "pressed_back": False,
                    "ready_rechecked": False,
                    "backoff_seconds": 0,
                },
            }

        triggered_count = 0
        recovery = {
            "attempted": False,
            "suppressed": None,
            "pressed_back": False,
            "ready_rechecked": False,
            "backoff_seconds": 0,
        }

        try:
            triggered_count = await self._process_events_once(page_source)

        except etree.XMLSyntaxError as e:
            self.logger.error(f"Failed to parse page_source: {str(e)}")
        except Exception:
            self.logger.error(f"Error in process_events: {traceback.format_exc()}")

        # 只要本轮触发了事件，就认为不在“连续未知页面”状态
        if triggered_count > 0:
            self._consecutive_unknown_pages = 0

        # 如果没有事件处理，说明进入了未知页面，默认按 press_back 尝试退出
        if triggered_count == 0:
            try:
                # 当 UI 正在被命令/后台任务占用时，禁止自动 back（否则会把命令弹窗当未知页面关掉）
                if self.runtime.is_ui_busy():
                    recovery["suppressed"] = "ui_busy"
                    self.logger.debug(
                        "No events triggered, but UI is busy (ui_lock locked). Skip auto press_back.")
                else:
                    recovery["attempted"] = True
                    self.handler.switch_to_app()
                    ready_source = await self._wait_page_source_ready_async(max_wait_s=2.5, interval_s=0.2)
                    if not ready_source:
                        recovery["suppressed"] = "page_source_not_ready"
                        # 切回瞬间 page_source 往往为空/是桌面，不应当按 back 误退出 App。
                        self.logger.debug(
                            "PageSource not ready after switch_to_app; skip auto press_back this round.")
                    else:
                        recovery["ready_rechecked"] = True
                        second_triggered = await self._process_events_once(ready_source)
                        if second_triggered == 0:
                            self.handler.press_back()
                            recovery["pressed_back"] = True
                            self.logger.warning("No events triggered, pressed back to exit unknown page")
                            self._consecutive_unknown_pages += 1
                            if self._consecutive_unknown_pages > 10:
                                backoff_s = min(10.0, 0.5 * (self._consecutive_unknown_pages - 10))
                                recovery["backoff_seconds"] = backoff_s
                                self.logger.warning(
                                    f"连续未知页面已达 {self._consecutive_unknown_pages} 次，"
                                    f"非阻塞退避 {backoff_s:.1f}s 后继续"
                                )
                                await asyncio.sleep(backoff_s)
                        else:
                            triggered_count = second_triggered
                            self._consecutive_unknown_pages = 0

            except Exception as e:
                self.logger.debug(f"Failed to press back: {str(e)}")

        return {
            "triggered_count": triggered_count,
            "recovery": recovery,
        }

    async def process_current_screen(self) -> dict:
        page_source = self.get_page_source()
        if not page_source:
            await asyncio.sleep(0.2)
            page_source = self.get_page_source()

        if not page_source:
            return {
                "page_source": None,
                "screen": self.describe_screen(""),
                "triggered_count": 0,
                "recovery": {
                    "attempted": False,
                    "suppressed": "no_page_source",
                    "pressed_back": False,
                    "ready_rechecked": False,
                    "backoff_seconds": 0,
                },
            }

        screen = self.describe_screen(page_source)
        reaction = await self.react_to_page(page_source)
        return {
            "page_source": page_source,
            "screen": screen,
            "triggered_count": reaction["triggered_count"],
            "recovery": reaction["recovery"],
        }

    async def process_events(self, page_source: str) -> int:
        return (await self.react_to_page(page_source))["triggered_count"]

    async def _process_events_once(self, page_source: str) -> int:
        if not page_source:
            return 0

        triggered_count = 0
        root = etree.fromstring(page_source.encode("utf-8"))

        keys_ordered: List[str] = []
        for k in self._PRIORITY_EVENT_KEYS:
            if k in self.element_to_event:
                keys_ordered.append(k)
        for k in self.element_to_event.keys():
            if k not in keys_ordered:
                keys_ordered.append(k)

        for element_key in keys_ordered:
            module_name = self.element_to_event[element_key]
            try:
                module = self.event_modules.get(module_name)
                xml_element = self._find_element_in_page_source(root, element_key, module)

                if xml_element is None:
                    continue

                if module and hasattr(module, "event"):
                    if isinstance(xml_element, list):
                        wrapper_list = [ElementWrapper(elem, self.handler, element_key) for elem in xml_element]
                        result = await module.event.handle(element_key, wrapper_list)
                        triggered_count += 1
                        if result is True:
                            self.logger.debug(
                                f"Event {element_key} returned True, stopping event processing"
                            )
                            break
                    else:
                        wrapper = ElementWrapper(xml_element, self.handler, element_key)
                        result = await module.event.handle(element_key, wrapper)
                        triggered_count += 1
                        if result is True:
                            self.logger.debug(
                                f"Event {element_key} returned True, stopping event processing"
                            )
                            break
            except Exception as e:
                self.logger.error(f"Error processing event for {element_key}: {str(e)}")

        return triggered_count

    async def _wait_page_source_ready_async(self, max_wait_s: float = 2.5, interval_s: float = 0.2) -> Optional[str]:
        """
        等待 page_source 可解析且 hierarchy 中已出现 Soul 包名（不依赖底部导航等锚点）。
        若当前为桌面或其它应用，会间歇调用 switch_to_app 直至超时。
        """
        deadline = time.time() + max_wait_s
        last_error = None
        soul_pkg = self._soul_package_name()

        while time.time() < deadline:
            try:
                src = self.handler.driver.page_source
                if not src:
                    self.handler.switch_to_app()
                    await asyncio.sleep(interval_s)
                    continue

                pkgs = self._packages_from_page_source(src)
                if pkgs is None:
                    last_error = "XMLSyntaxError"
                    await asyncio.sleep(interval_s)
                    continue

                if soul_pkg in pkgs:
                    return src

                launchers = set(self._launcher_packages())
                if pkgs & launchers:
                    self.logger.debug(
                        "PageSource foreground is not Soul (launcher detected); switching to Soul app"
                    )
                self.handler.switch_to_app()
                await asyncio.sleep(interval_s)
            except etree.XMLSyntaxError as e:
                last_error = e
                await asyncio.sleep(interval_s)
            except Exception as e:
                last_error = e
                await asyncio.sleep(interval_s)

        if last_error:
            self.logger.debug(f"PageSource ready wait timeout, last_error={last_error}")
        return None

    @with_driver_recovery
    def get_page_source(self) -> Optional[str]:
        """
        获取当前页面的 page_source

        Returns:
            页面源码 XML 字符串，失败返回 None
        """
        return self.handler.driver.page_source

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
