"""
元素包装器 - 包装从 page_source 解析出的 XML 元素

提供类似 WebElement 的接口，复用现有的 handler 方法
支持延迟获取真实的 WebElement（当需要进行操作时）
"""

from typing import Optional, List
from lxml import etree


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
        self._web_element = self._handler.try_find_element_plus(self._element_key, log=False)
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

