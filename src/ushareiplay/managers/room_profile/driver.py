"""内部端口：房间信息抽屉的物理动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    RoomProfileManager         引擎：谁决定开窗、谁决定关窗、窗口内按什么顺序做
        └── RoomProfileDrawerDriverPort  端口：Appium 细节止步于此
              ├── SoulDrawerDriver                    生产：包装 SoulHandler 的抽屉编排
              └── InMemoryRoomProfileDrawerDriver     测试：内存替身，pytest 离线可跑

端口只声明物理抽屉的四个原语：探测、点入口打开、点遮罩关闭、返回键。入口
key 的候选顺序（`DEFAULT_ENTRY_KEYS`）、`{theme}｜{title}` 不变量、冷却与草稿
都不属于这里 —— 那些是 `RoomProfileManager` 的决策，抽屉只是被驱动的东西。
因此新增一个字段、一种抽屉形态都不会让端口变宽。
"""

from abc import ABC, abstractmethod

# 窗口开着的证据：抽屉自身，或抽屉内任一控件。
DIALOG_KEYS = (
    'party_room_type_option',
    'party_recommendation_status',
    'edit_topic_entry',
    'edit_notice_entry',
    'slide_drawer',
)

# 打开抽屉的入口。chat_room_title 是既有调用点里最常用的入口，
# room_topic 指向同一个抽屉，作为兜底。
DEFAULT_ENTRY_KEYS = ('chat_room_title', 'room_topic')

#: 抽屉本体在 config.yaml 里的 key，也是正规关窗操作的目标。
DRAWER_KEY = 'slide_drawer'


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
