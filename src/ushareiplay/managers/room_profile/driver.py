"""内部端口：房间信息抽屉的物理动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    RoomProfileManager         引擎：谁决定开窗、谁决定关窗、窗口内按什么顺序做
        └── RoomProfileDrawerDriverPort  端口：Appium 细节止步于此
              ├── SoulDrawerDriver                    生产：包装 SoulHandler 的抽屉编排
              └── InMemoryRoomProfileDrawerDriver     测试：内存替身，pytest 离线可跑

端口只声明物理抽屉的原语：探测、点入口打开、点遮罩关闭、返回键，再加编辑
某个字段时那三步（点一个元素、等任意一个元素、往输入框里写字），以及房名编辑
入口那种「点元素里的某个高度」的手势。入口 key 的候选顺序（`DEFAULT_ENTRY_KEYS`）、
`{theme}｜{title}` 不变量、冷却与草稿都不属于这里 —— 那些是 `RoomProfileManager`
的决策，抽屉只是被驱动的东西。因此新增一种抽屉形态不会让端口变宽；而新增一个
字段只会复用这里已有的原语，不会再加方法 —— 这三个元素级原语是 #390 为了把话题
的点击 ritual 从 `TopicManager` 搬进来一次性加的，#391-#393 直接复用。
`click_element_at` 是唯一的后续增补：它复原的是一个**已上线**的手势（旧房名流程
的 0.25 高度点击），端口表达不出它就等于在没有任何人要求的情况下改掉了产品行为，
这比多一个原语更糟。
"""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

# 窗口开着的证据：抽屉自身，或抽屉内任一控件。
DIALOG_KEYS = (
    'party_room_type_option',
    'edit_topic_entry',
    'edit_notice_entry',
    'slide_drawer',
)

# 打开抽屉的入口。chat_room_title 是既有调用点里最常用的入口，
# room_topic 指向同一个抽屉，作为兜底。
DEFAULT_ENTRY_KEYS = ('chat_room_title', 'room_topic')

#: 抽屉本体在 config.yaml 里的 key。
DRAWER_KEY = 'slide_drawer'

#: 房间信息抽屉专门的关闭按钮 (iv_close)，不点击窗口上方。
ROOM_INFO_CLOSE_KEYS = ('room_info_close', 'close_button_1')


class RoomProfileDrawerDriverPort(ABC):
    """把房间信息抽屉的物理动作关在接口之后。"""

    @abstractmethod
    def is_open(self) -> bool:
        """抽屉当前是否开着（任一弹窗标志能解析到元素即为开着）。"""

    @abstractmethod
    def open_drawer(self, entry_key: str, *, error_message: str) -> dict:
        """点一次入口把抽屉打开。

        Args:
            entry_key: 入口 selector key。调用方负责决定按什么顺序试哪个入口。
            error_message: 打不开时写进返回值的文案。调用方原样传入自己面向
                用户的报错文本，以免统一入口后改变聊天气泡里的报错。

        Returns:
            成功为不含 `error` 的 dict（调用方只看这一点），失败为
            `{'error': error_message}`。实现不应抛出 UI 层异常：调用方靠这个
            返回值决定是否尝试下一个入口。
        """

    @abstractmethod
    def close_drawer(self) -> bool:
        """用 UI 正规关窗操作（点遮罩）关抽屉，成功返回 True。"""

    @abstractmethod
    def press_back(self) -> None:
        """按一次返回键。仅在正规关窗失败之后作为保底。"""

    @abstractmethod
    def click_element(self, key: str, *, timeout: int = 10) -> bool:
        """点一个可点击元素的**中心**；等不到就返回 False。

        抽屉里的编辑入口与确认按钮都走这里，Appium 的定位细节止步于适配器。
        """

    @abstractmethod
    def click_element_at(self, key: str, *, y_ratio: float, timeout: int = 10) -> bool:
        """点元素内某个纵向比例的位置（`y_ratio` 0.0=上缘，1.0=下缘）。

        与 `click_element` 分开而不是合成一个可选参数，因为「点中心」与
        「点 0.25 高度」是**两种不同的物理手势**，调用点必须一眼看出自己点的是
        哪一个 —— 合成一个参数等于让每个调用点自己判断「我是不是想点中心」。

        房名编辑入口（`title_edit_entry`）就是靠它复原随主题功能一起上线的
        0.25 高度点击（原先是 `gesture_handler.click_element_at(entry, y_ratio=0.25)`）。
        点不到元素、或者这一次坐标手势失败，都必须返回 False。
        """

    @abstractmethod
    def wait_for_any(self, keys: Sequence[str], *, timeout: int = 10) -> Optional[str]:
        """按 `keys` 的顺序等任意一个元素出现，返回命中的那个 key。

        顺序即优先级，与 `ElementFinder.wait_for_any_element` 一致：列表里排在前
        的先命中。都等不到则返回 None。
        """

    @abstractmethod
    def replace_text(self, key: str, text: str, *, timeout: int = 10) -> bool:
        """清空输入框并键入 `text`；元素等不到则返回 False。"""
