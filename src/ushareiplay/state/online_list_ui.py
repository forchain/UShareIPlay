from abc import ABC, abstractmethod


class OnlineListUI(ABC):
    """UISeen 端口：OnlineListScraper 抓取在线用户列表所需的 Soul UI 原语。

    Scraper 只依赖这个窄接口；具体实现由适配器提供（生产：SoulOnlineListUI；
    测试：FakeOnlineListUI）。
    """

    @abstractmethod
    def try_find_element(self, key, log=True):
        """按配置 key 查找元素，未找到返回 None。"""

    @abstractmethod
    def wait_for_element(self, key):
        """按配置 key 等待元素出现，超时返回 None。"""

    @abstractmethod
    def find_child_elements(self, parent, key):
        """在父元素内按配置 key 查找全部子元素。"""

    @abstractmethod
    def find_child_element(self, parent, key):
        """在父元素内按配置 key 查找单个子元素，未找到返回 None。"""

    @abstractmethod
    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=300):
        """执行一次滑动，返回是否成功。"""

    @abstractmethod
    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5):
        """按位置比例点击元素，返回是否成功。"""


class SoulOnlineListUI(OnlineListUI):
    """生产适配器：用 SoulHandler 的 element_finder / gesture_handler 实现端口。"""

    def __init__(self, handler=None):
        self._handler = handler

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    def try_find_element(self, key, log=True):
        return self.handler.element_finder.try_find_element(key, log=log)

    def wait_for_element(self, key):
        return self.handler.element_finder.wait_for_element(key)

    def find_child_elements(self, parent, key):
        return self.handler.element_finder.find_child_elements(parent, key)

    def find_child_element(self, parent, key):
        return self.handler.element_finder.find_child_element(parent, key)

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=300):
        return self.handler.gesture_handler.swipe(start_x, start_y, end_x, end_y, duration_ms=duration_ms)

    def click_element_at(self, element, x_ratio=0.5, y_ratio=0.5):
        return self.handler.gesture_handler.click_element_at(element, x_ratio, y_ratio)
