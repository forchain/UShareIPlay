"""
元素包装器 - 包装从 page_source 解析出的 XML 元素

提供类似 WebElement 的接口，复用现有的 handler 方法
支持延迟获取真实的 WebElement（当需要进行操作时）
"""

from typing import Optional, List
from lxml import etree

from ushareiplay.core.chat_intake import format_quoted_message

# 引用回复视图的默认资源 id；可经 config.yaml 的 soul.elements 覆盖
# （UI 选择器统一放在配置中，见 CLAUDE.md）
DEFAULT_REPLY_VIEW_ID = "gReplyView"
DEFAULT_REPLY_CONTENT_ID = "tvReplyContent"
# 从正文向上探测引用视图的最大层数；引用视图与正文同属一条消息的行容器
MAX_REPLY_ANCESTOR_LEVELS = 4


def _visible_text(node) -> str:
    """content-desc first, then text — the visible content of an XML node."""
    content_desc = node.get("content-desc")
    if content_desc and content_desc != "null":
        return content_desc
    return node.get("text") or ""


def _matches_resource_id(node, resource_id: str) -> bool:
    """True when *node* carries *resource_id*, bare or package-qualified."""
    node_id = node.get("resource-id") or ""
    if not node_id:
        return False
    return node_id == resource_id or node_id.endswith(f"/{resource_id}")


def _find_node_with_resource_id(node, resource_id: str):
    """First node (self or descendant) carrying *resource_id*, or None."""
    for candidate in node.iter():
        if _matches_resource_id(candidate, resource_id):
            return candidate
    return None


def _is_the_only_one(node, resource_id: str) -> bool:
    """True when exactly one node (self or descendant) carries *resource_id*.

    Bails out at the second match, so scanning a wide container stays cheap.
    """
    matches = 0
    for candidate in node.iter():
        if _matches_resource_id(candidate, resource_id):
            matches += 1
            if matches > 1:
                return False
    return matches == 1


def _reply_view_text(reply_view, reply_content_id: str) -> Optional[str]:
    node = _find_node_with_resource_id(reply_view, reply_content_id)
    if node is None:
        # Tolerate a reply view that carries the quoted text on the view itself.
        node = reply_view
    return _visible_text(node).strip() or None


def composed_message_text(wrapper) -> str:
    """The message text an event should treat as this row's content.

    Quoted Message context is composed in for an ElementWrapper carrying a reply
    view; other wrappers (e.g. test doubles) contribute their plain ``content``.
    """
    quoted = wrapper.quoted_message() if isinstance(wrapper, ElementWrapper) else None
    return format_quoted_message(wrapper.content or "", quoted)


class ElementWrapper:
    """
    元素包装器，包装从 page_source 解析出的 lxml Element
    
    提供与 WebElement 类似的接口，方便在事件处理中使用
    """

    def __init__(self, xml_element: etree._Element, handler=None, element_key: str = None):
        """
        初始化元素包装器
        
        Args:
            xml_element: lxml 解析出的 XML 元素
            handler: AppHandler 实例（可选），用于延迟获取真实的 WebElement
            element_key: 元素的配置 key（可选），用于通过 handler 查找真实元素
        """
        self._xml_element = xml_element
        self._handler = handler
        self._element_key = element_key
        self._web_element = None  # 延迟加载的真实 WebElement

    @property
    def text(self) -> str:
        """获取元素文本"""
        return self._xml_element.get('text', '')

    @property
    def content(self) -> str:
        """获取元素内容，优先使用 content-desc，如果没有则使用 text"""
        return _visible_text(self._xml_element)

    @property
    def tag(self) -> str:
        """获取元素标签名"""
        return self._xml_element.tag

    def get_attribute(self, name: str) -> Optional[str]:
        """
        获取元素属性
        
        Args:
            name: 属性名称
            
        Returns:
            属性值，如果不存在则返回 None
        """
        return self._xml_element.get(name)

    def get_web_element(self):
        """
        延迟获取真实的 WebElement
        
        当需要对元素进行点击、输入等操作时，通过 handler 获取真实的 WebElement
        
        Returns:
            WebElement 或 None（如果无法获取）
        """
        if self._web_element is not None:
            return self._web_element

        if self._handler is None or self._element_key is None:
            return None

        # 通过 handler 获取真实的 WebElement
        self._web_element = self._handler.element_finder.try_find_element(self._element_key, log=False)
        return self._web_element

    def click(self) -> bool:
        """
        点击元素
        
        Returns:
            是否成功点击
        """
        web_element = self.get_web_element()
        if web_element:
            try:
                web_element.click()
                return True
            except Exception:
                return False
        return False

    def find_child_element(self, xpath: str) -> Optional['ElementWrapper']:
        """
        在当前元素下查找子元素
        
        Args:
            xpath: 相对 XPath 表达式
            
        Returns:
            ElementWrapper 或 None
        """
        try:
            result = self._xml_element.xpath(xpath)
            if result:
                return ElementWrapper(result[0], self._handler)
            return None
        except Exception:
            return None

    def find_child_elements(self, xpath: str) -> List['ElementWrapper']:
        """
        在当前元素下查找所有匹配的子元素
        
        Args:
            xpath: 相对 XPath 表达式
            
        Returns:
            ElementWrapper 列表
        """
        try:
            results = self._xml_element.xpath(xpath)
            return [ElementWrapper(elem, self._handler) for elem in results]
        except Exception:
            return []

    def is_displayed(self) -> bool:
        """检查元素是否可见"""
        # 从 XML 属性判断
        displayed = self._xml_element.get('displayed')
        if displayed is not None:
            return displayed.lower() == 'true'
        # 检查 bounds 属性
        bounds = self._xml_element.get('bounds')
        return bounds is not None and bounds != '[0,0][0,0]'

    def is_enabled(self) -> bool:
        """检查元素是否启用"""
        enabled = self._xml_element.get('enabled')
        if enabled is not None:
            return enabled.lower() == 'true'
        return True

    def is_clickable(self) -> bool:
        """检查元素是否可点击"""
        clickable = self._xml_element.get('clickable')
        if clickable is not None:
            return clickable.lower() == 'true'
        return False

    def _element_id(self, config_key: str, default: str) -> str:
        """Resolve a UI resource id from config.yaml `soul.elements`."""
        config = getattr(self._handler, "config", None)
        if isinstance(config, dict):
            soul = config.get("soul")
            elements = soul.get("elements") if isinstance(soul, dict) else None
            selector = elements.get(config_key) if isinstance(elements, dict) else None
            if isinstance(selector, str) and selector.strip():
                return selector.strip()
        return default

    def quoted_message(self) -> Optional[str]:
        """Return the Quoted Message this element replies to, or None.

        The message content anchor points at the sender's own TextView; the
        referenced snippet lives in a sibling reply view inside the same message
        row. The row is found by walking up until an ancestor holds exactly one
        node like this one — anything wider is the chat list, where reply views
        belong to other rows and must not leak into this one.
        """
        own_id = self.get_attribute("resource-id")
        if not own_id:
            return None

        reply_view_id = self._element_id("message_reply_view", DEFAULT_REPLY_VIEW_ID)
        reply_content_id = self._element_id("message_reply_content", DEFAULT_REPLY_CONTENT_ID)
        try:
            node = self._xml_element
            for _ in range(MAX_REPLY_ANCESTOR_LEVELS):
                container = node.getparent()
                if container is None:
                    return None
                node = container
                if not _is_the_only_one(container, own_id):
                    # Ancestors only get wider, so no level above can be a row.
                    return None
                reply_view = _find_node_with_resource_id(container, reply_view_id)
                if reply_view is None:
                    continue
                reply_text = _reply_view_text(reply_view, reply_content_id)
                if reply_text:
                    return reply_text
            return None
        except Exception:
            return None

    def context_text(self, *, ancestor_levels: int = 3) -> str:
        """Return nearby snapshot text for events that need dialog context."""
        try:
            container = self._xml_element
            for _ in range(ancestor_levels):
                parent = container.getparent()
                if parent is None:
                    break
                container = parent
            values = []
            for node in container.iter():
                for attribute in ("text", "content-desc"):
                    value = node.get(attribute)
                    if value and value != "null":
                        values.append(value)
            return "\n".join(values)
        except Exception:
            return ""

    @property
    def bounds(self) -> Optional[dict]:
        """
        获取元素边界
        
        Returns:
            包含 x, y, width, height 的字典，或 None
        """
        bounds_str = self._xml_element.get('bounds')
        if not bounds_str:
            return None
        
        try:
            # bounds 格式: [x1,y1][x2,y2]
            import re
            match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
            if match:
                x1, y1, x2, y2 = map(int, match.groups())
                return {
                    'x': x1,
                    'y': y1,
                    'width': x2 - x1,
                    'height': y2 - y1
                }
        except Exception:
            pass
        return None

    def __repr__(self) -> str:
        resource_id = self.get_attribute('resource-id') or ''
        text = self.text[:20] if self.text else ''
        return f"<ElementWrapper tag={self.tag} resource-id={resource_id} text={text}>"
