"""内部端口：Soul 在线用户抽屉的物理动作。

端口与适配器的分工（ADR-0009 的构造注入约定在本模块的体现）：

    OnlineDrawerManager          引擎：要不要开、开不了给什么错、关不关
        └── OnlineDrawerDriverPort  端口：Appium 细节止步于此
              ├── SoulOnlineDrawerDriver        生产：包装 SoulHandler 的手势
              └── InMemoryOnlineDrawerDriver     测试：内存替身，pytest 离线可跑

## 为什么这个端口里没有 `press_back`

房间档案的端口留了 `press_back` 作为保底，这里**刻意不留**：spec #426 的问题
陈述 #1 记的正是盲按返回会误退出派对房间（真机 09-28 18:07/20:46）。在线用户
抽屉有专门的 `ivClose` 关闭按钮，没有理由去赌那个键。端口里不存在这个原语，
`drawer_session` 就在**结构上**不可能发出盲按，而不是靠一条约定约束住自己。

## 哪些决策不属于这里

以下全部是 `OnlineDrawerManager` 的判断，抽屉只是被驱动的东西：什么时候需要打开、
打开失败给调用方什么文案、什么时候放弃、**命名域解析**（DB canonical 名 ->
Soul UI 可见昵称）、以及这次会话要不要负责关窗。因此新增一种抽屉形态只会改这里
的 key 常量，不会让端口变宽；而 #432/#435/#438/#439 需要的新原语会在各自需要时
再加 —— 端口不为还没人要求的行为预留位置。

## 为什么全部是 async

本端口的调用方 `OnlineDrawerManager` 是异步的，而「等抽屉落定」「滑完等列表
停稳」本身就是等待：把它们留在同步接口里会让适配器没法如实表达物理时序，只能
把 settle 塞给调用方，那才是把 Appium 的时序知识漏回引擎层。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

#: 在线用户抽屉本体。出现即说明抽屉开着（进场判定与「已经开着就复用」都靠它）。
ONLINE_CONTAINER_KEY = 'online_users'

#: 打开抽屉的入口：房间里显示「N 人在线」的那个控件。
ENTRY_KEY = 'user_count'

#: 抽屉里一行在线用户的外壳，以及行内的两个读数。
ROW_CONTAINER_KEY = 'user_container'
ROW_NAME_KEY = 'online_user'
ROW_FOLLOW_STATE_KEY = 'follow_state'

#: 抽屉专门的关闭按钮。两个 key 指向同一个 resource-id（`ivClose`），存在两份是
#: 沿用既有实现的历史包袱；按顺序试完就是这里的全部「安全兜底」——没有第三个手势。
CLOSE_KEYS = ('online_users_close', 'close_button')

#: 列表到底的提示。`is_at_end` 负责判它显不显示，要不要就此停下仍是调用方的循环决策。
END_OF_LIST_KEY = 'no_more_data'

#: 滑动时长（毫秒）。沿用既有实现的 800ms：默认的快滑会让 RecyclerView 惯性飞滚，
#: 跳过还没渲染的行；慢一点宁可多滑一次，也不要漏掉一个在线用户。
DEFAULT_SCROLL_DURATION_MS = 800

#: 等抽屉自己出现 / 落定的默认上限（秒）。
DEFAULT_SETTLE_TIMEOUT = 10

#: 抽屉出现之后的落定静默（秒）：容器在 dump 里不等于行已经渲染出来。
SETTLE_SECONDS = 0.4

#: 滑完之后等列表停稳的静默（秒），同样是为了别读到滑动途中的画面。
POST_SCROLL_SETTLE_SECONDS = 0.6


@dataclass(frozen=True)
class MemberRow:
    """在线用户列表里一行的**驱动中立**读数。

    刻意是值而不是 WebElement 的句柄：Appium 的元素对象一旦逃出适配器，就会把
    `StaleElementReferenceException` 泄漏到引擎层 —— 抽屉里的行活不过一次滚动，
    拿着它跨越 await 点就是等着炸。这里只带**当场读到的文本**。

    Attributes:
        visible_name: UI 上显示的昵称（分身名），这是列表里唯一能定位到人的东西。
        follow_state: 关注关系文案（密友 / 我关注的 / 关注了我），读不到时是 None。
    """

    visible_name: str
    follow_state: Optional[str] = None


class OnlineDrawerDriverPort(ABC):
    """把在线用户抽屉的物理动作关在接口之后。"""

    @abstractmethod
    async def is_open(self) -> bool:
        """抽屉当前是否开着（容器元素在页面上即为开着）。"""

    @abstractmethod
    async def open(self, *, error_message: str) -> dict:
        """点一次 `user_count` 入口把抽屉打开。

        Args:
            error_message: 打不开时写进返回值的文案。调用方原样传入自己面向用户的
                报错文本，以免统一入口后改变聊天气泡里的报错。

        Returns:
            成功为不含 `error` 的 dict（调用方只看这一点），失败为
            `{'error': error_message}`。实现不应抛出 UI 层异常 —— 调用方靠这个
            返回值决定是否放弃整个会话。
        """

    @abstractmethod
    async def close(self) -> bool:
        """按 `CLOSE_KEYS` 的顺序点专门的 `ivClose` 关闭按钮，成功返回 True。

        两个按钮都点不到时返回 False，让**调用方**决定怎么办。这里刻意没有别的
        兜底手势：见模块开头的「为什么这个端口里没有 press_back」。
        """

    @abstractmethod
    async def wait_for_settle(self, *, timeout: int = DEFAULT_SETTLE_TIMEOUT) -> bool:
        """等在线用户容器出现并渲染稳定。

        Returns:
            容器等不到或落定超时返回 False。调用方据此判定「抽屉还没准备好」，
            而不是继续往一个半开的抽屉里做动作。
        """

    @abstractmethod
    async def scroll_container(
        self, *, duration_ms: int = DEFAULT_SCROLL_DURATION_MS
    ) -> bool:
        """在在线用户容器内往下滑一页（手指向上，列表向下滚）。

        Returns:
            是否真的滑动了。滑不动（手势失败）时返回 False，调用方据此停止循环。
        """

    @abstractmethod
    async def find_member_row(self, visible_username: str) -> Optional[MemberRow]:
        """在**当前已渲染**的行里找某个昵称，找到返回那一行，读不到返回 None。

        只看此刻渲染出来的行，不自己滚 —— 「找不到就再滑一页」是循环决策，属于
        `OnlineDrawerManager`。

        Args:
            visible_username: **UI 可见昵称**（分身名），不是 DB 里的 canonical 名。
                调用方必须先用 `OnlineDrawerManager.resolve_visible_username` 解析，
                拿 canonical 名直接比 UI 文本永远不相等。
        """

    @abstractmethod
    async def read_online_count(self) -> Optional[int]:
        """读房间里「N 人在线」那个控件，报出它写的在线人数。

        必须在**抽屉打开之前**读：抽屉一旦盖上来，这个控件就被挡住了。它是抓取结果
        的**期望值**，用来和列表里真抓到的行数对账。

        Returns:
            文案里第一段数字解析出的 int；控件读不到、文案里没有数字、或者压根没有
            App 时一律返回 None —— 「读不到人数」和「人数为 0」必须分得开，否则会把
            对账变成拿 0 去比。
        """

    @abstractmethod
    async def visible_member_rows(self) -> list:
        """当前屏幕**已渲染**的整页在线用户，每行带昵称与关注关系。

        一次读回整页，因为翻页判据是「这一页有没有带来新的人」，逐行问端口等于把
        Appium 的多次 dump 搬进引擎。同样**不自己滚**：滑不滑、什么时候停都是
        `OnlineDrawerManager` 的循环决策。

        Returns:
            `MemberRow` 列表（空列表表示这一页还没有行）。读坏的单行被跳过，不影响
            整页；元素对象一个也不外泄。
        """

    @abstractmethod
    async def is_at_end(self) -> bool:
        """列表是否已经到底（`no_more_data` 提示已显示）。

        只判「用户看得见」：提示元素留在 dump 里不等于它渲染出来了。这里也只回答
        「到没到」，要不要就此停下是调用方的循环决策。
        """

