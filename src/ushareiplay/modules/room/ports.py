"""房间包的出站端口：钩子命令持久化、消息出口、在线名单与管理状态存储。

端口只描述房间业务需要的能力；生产实现在 `adapters/`，测试替身在 `tests/fakes/`。
"""

from abc import ABC, abstractmethod
from typing import Optional, Sequence, Set

from ushareiplay.modules.room.domain import HookCommand


class UserEventHookRepository(ABC):
    """用户事件钩子命令的持久化；事件类型是第一等参数。

    查询口径（single-id / alias-group）由 `registry` 按事件类型声明，
    实现必须照做。
    """

    @abstractmethod
    async def create(self, event_type: str, username: str, command: str) -> HookCommand:
        """为用户新建一条该事件类型的命令（写 canonical 主账号）。"""

    @abstractmethod
    async def get_by_username(self, event_type: str, username: str) -> list[HookCommand]:
        """该用户在此事件类型下的全部命令，按 id 升序。"""

    @abstractmethod
    async def get_all_ordered(self, event_type: str) -> list[HookCommand]:
        """全部用户的命令，按 id 升序。"""

    @abstractmethod
    async def get_by_id(self, event_type: str, command_id: int) -> Optional[HookCommand]:
        """按 id 取单条命令。"""

    @abstractmethod
    async def delete_by_id(self, event_type: str, command_id: int) -> bool:
        """按 id 删除单条命令，返回是否真的删掉了。"""

    @abstractmethod
    async def delete_all_by_username(self, event_type: str, username: str) -> int:
        """清空该用户在此事件类型下的全部命令，返回删除条数。"""


class HookCommandSink(ABC):
    """钩子命令的入队出口：交给运行时队列，由队列 drain 时执行。"""

    @abstractmethod
    async def enqueue(self, content: str, nickname: str) -> None:
        """投递一条待执行命令。"""


class PresenceQuery(ABC):
    """当前在线用户集合的只读查询。"""

    @abstractmethod
    def get_online_users(self) -> Set[str]:
        """在线用户名集合（副本）。"""

    @abstractmethod
    def is_user_online(self, username: str) -> bool:
        """该用户当前是否在线。"""


class MemoryConsolidationSink(ABC):
    """用户离开时的记忆沉淀调度。"""

    @abstractmethod
    def schedule_user(self, username: str) -> None:
        """为某个用户安排一次记忆沉淀。"""


class RoomStateStore(ABC):
    """房间状态的跨进程持久化（预期房间 ID）。"""

    @abstractmethod
    def load_expected_party_id(self) -> Optional[str]:
        """读取上次显式设置的预期房间 ID。"""

    @abstractmethod
    def save_expected_party_id(self, party_id: Optional[str]) -> None:
        """持久化预期房间 ID。"""


class OnlineListSource(ABC):
    """从在线用户列表 UI 刷新在线用户集合。"""

    @abstractmethod
    async def refresh_online_users(self, target_count: Optional[int] = None) -> bool:
        """按人数（可缺省）抓取在线名单；失败返回 False。"""


# --------------------------------------------------------------------------
# 房间档案：抽屉与派对设置面板
# --------------------------------------------------------------------------

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

        Returns:
            成功为不含 `error` 的 dict，失败为 `{'error': error_message}`。
        """

    @abstractmethod
    def close_drawer(self) -> bool:
        """用 UI 正规关窗操作（点遮罩）关抽屉，成功返回 True。"""

    @abstractmethod
    def press_back(self) -> None:
        """按一次返回键。仅在正规关窗失败之后作为保底。"""

    @abstractmethod
    def click_element(self, key: str, *, timeout: int = 10) -> bool:
        """点一个可点击元素的中心；等不到就返回 False。"""

    @abstractmethod
    def click_element_at(self, key: str, *, y_ratio: float, timeout: int = 10) -> bool:
        """点元素内某个纵向比例的位置（房名编辑入口的 0.25 高度点击）。"""

    @abstractmethod
    def wait_for_any(self, keys: Sequence[str], *, timeout: int = 10) -> Optional[str]:
        """按 `keys` 的顺序等任意一个元素出现，返回命中的那个 key。"""

    @abstractmethod
    def replace_text(self, key: str, text: str, *, timeout: int = 10) -> bool:
        """清空输入框并键入 `text`；元素等不到则返回 False。"""


class RoomProfileSurfacePort(ABC):
    """抽屉之外、房间档案需要的只读屏幕判定与前台切换。"""

    @abstractmethod
    def switch_to_app(self) -> bool:
        """把 Soul App 切到前台；失败返回 False。"""

    @abstractmethod
    def read_room_title(self) -> Optional[str]:
        """读一次屏幕上的房名：优先抽屉内那一行，其次主界面标题。"""

    @abstractmethod
    def read_notice_text(self) -> str:
        """读一次抽屉里当前公告的文案；读不到返回空串。"""

    @abstractmethod
    def read_row_text(self, key: str, *, wait: bool = False) -> str:
        """读一次抽屉里某一行显示的文案；读不到返回空串。"""


PARTY_SETTING_BUTTON_KEY = 'party_setting_button'
RECOMMENDATION_STATUS_KEY = 'party_setting_recommendation_status'
RECOMMENDATION_OPTION_KEYS = {
    True: 'party_recommendation_open',
    False: 'party_recommendation_close',
}
PARTY_SETTING_CLOSE_KEY = 'party_setting_close'
PARTY_SETTING_TITLE_KEY = 'party_setting_title'
PARTY_SETTING_CONTAINER_KEY = 'party_setting_container'

DEFAULT_MAX_SWIPES = 5


class PartySettingsDriverPort(ABC):
    """把派对设置面板的物理动作关在接口之后。"""

    @abstractmethod
    def is_open(self) -> bool:
        """设置面板当前是否开着。"""

    @abstractmethod
    def open(self) -> bool:
        """点设置按钮并把面板打开；已经开着时直接返回 True。"""

    @abstractmethod
    def reveal_recommendation_status(self, *, max_swipes: int = DEFAULT_MAX_SWIPES) -> bool:
        """在面板里翻页查找推荐状态项，找到（或已经在屏幕上）返回 True。"""

    @abstractmethod
    def click_recommendation_status(self) -> bool:
        """点推荐状态那一行，呼出二级选项弹窗。"""

    @abstractmethod
    def click_recommendation_option(self, enabled: bool) -> bool:
        """在二级弹窗里点「所有人」（True）或「关闭推荐分发」（False）。"""

    @abstractmethod
    def close(self) -> None:
        """关闭设置面板：优先点 ivClose，关不掉时用返回键兜底。"""

    @abstractmethod
    def press_back(self) -> None:
        """按一次返回键。"""
