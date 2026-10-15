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

# ---------------------------------------------------------------------------
# 资料卡与私聊（#435）
# ---------------------------------------------------------------------------
#
# 资料卡是抽屉**之上**的一层弹窗：点开在线用户抽屉里的某一行，卡片就盖在抽屉上。
# 它与抽屉共用同一个 `ivClose` 关闭按钮（见上面的 `CLOSE_KEYS`），所以「收起资料卡」
# 与「关掉抽屉」在物理上是同一个手势 —— 而且是**唯一**可用的那一个：这里同样没有
# 盲按返回，卡片关不掉就只能记警告保持原状。

#: 卡片上的昵称，用作「资料卡还在不在」的判据。
#:
#: 刻意不用「送礼物」「管理邀请」这类按钮：它们对某些账号根本不渲染，拿一个可能缺席
#: 的按钮当标志，会把「卡片已经收好了」误判成「卡片还悬着」。
PROFILE_CARD_NICKNAME_KEY = 'sender_nickname'

#: 卡片上的头像。它同时是「点头像进入该用户主页」的入口。
PROFILE_CARD_AVATAR_KEY = 'sender_avatar'

#: 用户主页上的「私聊」按钮，以及私聊页的输入框与发送按钮。
PRIVATE_CHAT_BUTTON_KEY = 'private_chat_button'
PRIVATE_MESSAGE_INPUT_KEY = 'private_message_input'
PRIVATE_MESSAGE_SEND_KEY = 'private_message_send'

#: 回到派对房间的入口，按优先级尝试。`item_left_back` 是个性主页左上角的返回，点完
#: 还要再点一次标题栏返回才落回房间（见 `return_to_room`）。
ROOM_ENTRY_KEYS = ('private_room_entry', 'floating_entry', 'item_left_back')

#: 点了 `item_left_back` 之后要补的那一下标题栏返回。
TITLEBAR_BACK_KEY = 'titlebar_back_ivbtn'

# ---------------------------------------------------------------------------
# 送礼（#438）
# ---------------------------------------------------------------------------
#
# 送礼弹窗是盖在资料卡**之上**的一层弹窗：先点资料卡上的「送礼物」，弹窗才出现。
# 因此整条链路是 抽屉 -> 资料卡 -> 送礼弹窗 ->（小黄鸭即时送 或 赠送/使用 + 确认），
# 而收尾要按**相反的顺序**分层收：先收弹窗，再收卡片（收卡片时抽屉一起收）。
#
# 与 #435 一样，这里不提供盲按返回：旧实现收不了弹窗时就 `press_back`，把那层资料卡
# 与抽屉留在屏幕上，下一次盲按返回会把它们连同派对房间一起带走（问题陈述 #1）。

#: 资料卡上的「送礼物」入口。
GIFT_ENTRY_KEY = 'send_gift'

#: 送礼弹窗上两个互斥的动作按钮：商店礼物点「赠送」，背包道具点「使用」。
#: 两者只会出现一个，这个事实本身就是弹窗是否已经起来的判据。
GIFT_ACTION_KEYS = ('give_gift', 'use_item')

#: `gift_popup_action` 的两个取值。用常量而不是裸字符串：这两个 key 同时出现在端口
#: 签名与引擎的分支判断里，共用一份定义才不会在 App 改 key 时漏改一处。
GIFT_ACTION_GIVE = 'give_gift'
GIFT_ACTION_USE = 'use_item'

#: 弹窗里当前选中礼物的名字（初级/中级/高级福袋，或背包为空时的小黄鸭）。
GIFT_ITEM_NAME_KEY = 'luck_item'

#: 选中礼物旁的灵魂力读数（`+12灵魂力`）。只进日志，因此读不到不算失败。
GIFT_SOUL_POWER_KEY = 'soul_power'

#: 背包道具点「使用」之后那道确认框里的「确认」。
GIFT_CONFIRM_KEY = 'confirm_use'

#: 送礼弹窗自己的页内关闭键组，按顺序试完为止 —— 没有第三个手势，也没有盲按返回。
#:
#: `close_button_1`（`iv_close`）是「我送给 TA」那类送礼弹窗自己的 X；`close_button`
#: （`ivClose`）是资料卡与抽屉共用的那个 X，也是 #435 收资料卡用的手势。两个都点不到
#: 就返回 False 让调用方记警告，保持原状等下一轮恢复 —— 屏幕上多一层弹窗只是难看，
#: 盲按返回退出派对房间才是事故。
GIFT_POPUP_CLOSE_KEYS = ('close_button_1', 'close_button')

#: 送礼弹窗各步的等待上限（秒）：等入口可点、等弹窗起来、等确认框出现、等弹窗消失。
#: 沿用旧实现里 `wait_for_element_clickable` / `wait_for_any_element` / `wait_for_element`
#: 的默认 10 秒，逐字保留而不是收紧 —— 真机上这些等待本来就踩过线。
GIFT_POPUP_TIMEOUT = 10

#: 头像点击的纵向比例。沿用旧实现的 0.7：卡片上的头像是圆图，点正中会落在圆外的空白
#: 边距里 —— 这是真机调出来的值，迁移时逐字保留，不顺手改成 0.5。
AVATAR_CLICK_Y_RATIO = 0.7

#: 等资料卡弹出、私聊各步、找返回入口的等待上限（秒）。分别沿用旧实现的 5 / 5 / 3 秒。
PROFILE_CARD_TIMEOUT = 5
PRIVATE_CHAT_TIMEOUT = 5
ROOM_RETURN_TIMEOUT = 3


# ---------------------------------------------------------------------------
# 房管（#439）
# ---------------------------------------------------------------------------
#
# 房管开关是资料卡上的**一枚**控件：文案是「管理邀请」时点下去是邀请，是「解除管理」
# 时点下去是解除。因此「现在是不是房管」这个判断必须由 `OnlineDrawerManager` 拿着
# 文案去做，端口只负责读出文案、只负责点下去 —— 把这个判断塞进端口，就等于让 App 的
# 控件词汇渗进引擎层，而它本来该由聊天命令的那句「已经 / 还不是管理员」来决定。
#
# 确认框是盖在资料卡**之上**的一层弹窗，所以收尾要与 #438 的送礼弹窗一样按相反顺序
# 分层收：先收确认框，再收资料卡（收卡片时抽屉一起收）。

#: 资料卡上的房管开关（邀请与解除管理共用同一枚控件）。
ADMIN_INVITE_KEY = 'manager_invite'

#: 房管开关此刻写的两种文案。App 的文案保持原样，不在这里翻成布尔值：它们既进判断
#: 分支，也会被逐字抄进聊天回复，保持一处定义才不会在 App 改文案时漏改一处。
ADMIN_LABEL_INVITE = '管理邀请'      # 现在还不是房管，点下去是邀请
ADMIN_LABEL_DISMISS = '解除管理'     # 现在已经是房管，点下去是解除

#: `confirm_admin_action` 的两个取值。与 `GIFT_ACTION_*` 同一个理由用常量：这两个
#: key 同时出现在端口签名、适配器的按钮映射与引擎的分支判断里，共用一份定义才不会
#: 在 App 改 key 时漏改一处。
ADMIN_ACTION_INVITE = 'invite'
ADMIN_ACTION_DISMISS = 'dismiss'

#: 确认框里两个动作各自的按钮。刻意不用 key 列表而用映射：邀请与解除在 App 上**不是**
#: 同一个控件（`confirm_dismiss` 只认文案「确认解除」），所以「点哪个按钮」取决于调用
#: 方要做哪个动作 —— 这是引擎的判断，而「这个动作对应哪个 resource-id」是 App 的事。
ADMIN_CONFIRM_KEYS = {
    ADMIN_ACTION_INVITE: 'confirm_invite',
    ADMIN_ACTION_DISMISS: 'confirm_dismiss',
}

#: 确认框可能悬着时，按顺序试完为止的页内 X。
#:
#: 刻意与 `GIFT_POPUP_CLOSE_KEYS` 取同样的两个 key：`config.yaml` 里目前**没有**房管
#: 确认框专属的关闭键，而 #438 已经确认过这一对在真机上确实能收掉弹窗。这里另起一个名字
#: 而不是直接复用那个常量，是为了让两条流程在真机上验出各自的键之后可以各改各的，
#: 不用回头去动对方已经验过的值。
ADMIN_CONFIRM_CLOSE_KEYS = ('close_button_1', 'close_button')

#: 房管各步的等待上限（秒）：等开关可点、等确认框出现、等确认框消失。逐字沿用旧
#: `AdminManager` 里 `wait_for_element_clickable` / `wait_for_element_disappear` 的默认
#: 10 秒，不收紧 —— 真机上这些等待本来就踩过线。
ADMIN_CONTROL_TIMEOUT = 10


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

    # ------------------------------------------------------------------
    # 资料卡（#435）
    # ------------------------------------------------------------------

    @abstractmethod
    async def open_member_profile(self, visible_username: str) -> bool:
        """在**当前已渲染**的行里点昵称那一行，把资料卡打开。

        「找行」与「点行」必须是一次手势，不能拆开：`find_member_row` 交回来的是
        `MemberRow` 这样的**值**，抽屉里的行活不过一次滚动，把行元素跨过 await 点带到
        点下去那一刻，等的是 `StaleElementReferenceException`。同理也不自己滚 ——
        「找不到就再滑一页」仍是调用方的循环决策。

        Args:
            visible_username: **UI 可见昵称**（分身名）。canonical 名在这里永远找不到人。

        Returns:
            卡片是否真的出现了。没找到那一行、或点了卡片没弹出来，都返回 False ——
            调用方据此走自己的失败路径，**不要**接着往下点资料卡上的东西。
        """

    @abstractmethod
    async def is_profile_card_open(self) -> bool:
        """资料卡此刻是否还盖在抽屉上。"""

    @abstractmethod
    async def dismiss_profile_card(self) -> bool:
        """把资料卡收回房间，点的是它与抽屉共用的 `ivClose`。

        卡片本来就没开着时直接返回 True（幂等）：「已经回到房间」和「收好了」是同一件
        事，调用方不必先问一遍。

        Returns:
            卡片确实不在了返回 True；关闭按钮点不到、卡片赖着不走返回 False，让**调用方**
            记警告 —— 这里同样没有第二条兜底手势，见模块开头的「为什么没有 press_back」。
        """

    # ------------------------------------------------------------------
    # 私聊（#435）
    # ------------------------------------------------------------------

    @abstractmethod
    async def open_member_home(self) -> bool:
        """点资料卡上的头像，进入该用户主页。

        点的是**卡片**上的头像，因此调用方要先确认卡片是自己的；这一步之后页面已经换掉，
        资料卡不在屏幕上了。
        """

    @abstractmethod
    async def open_private_chat_page(self) -> bool:
        """点用户主页上的「私聊」按钮，进入与该用户的私聊页。"""

    @abstractmethod
    async def type_private_message(self, text: str) -> bool:
        """在私聊输入框里输入文字（不发送）。

        与发送分成两个原语：输入框读不到和发送按钮读不到是两件事，调用方给它们的
        报错文案也不一样。
        """

    @abstractmethod
    async def submit_private_message(self) -> bool:
        """点私聊页的发送按钮，把输入框里的文字发出去。"""

    @abstractmethod
    async def return_to_room(self) -> bool:
        """回到派对房间，只用页面上指得出来的入口。

        依次找 `ROOM_ENTRY_KEYS`：私聊页顶上挂着「回到房间」的动画按钮，房间里常驻的
        `floating_entry`，以及个性主页左上角的 `item_left_back`（这个要点两下，见下）。

        刻意**不**提供退回房间的第二条路径。这里已经是「不在房间里」的状态，盲按返回
        会退到上一个页面甚至退出派对房间（spec #426 问题陈述 #1）；宁可让调用方记一条
        警告，下一轮恢复流程去收拾。

        Returns:
            回到房间了返回 True；三个入口都读不到、或 `item_left_back` 之后没等到标题栏
            返回，返回 False。
        """

    # ------------------------------------------------------------------
    # 送礼（#438）
    # ------------------------------------------------------------------

    @abstractmethod
    async def open_gift_entry(self) -> bool:
        """点资料卡上的「送礼物」，把送礼弹窗叫起来。

        只负责「点下去」：弹窗起没起来由下一次 `gift_popup_action` 回答，因为那两件事
        在旧实现里是两条不同的报错文案，合成一步会把聊天气泡里的话改掉。

        Returns:
            点了返回 True；资料卡上没有这个入口（本来就没渲染）返回 False。
        """

    @abstractmethod
    async def gift_popup_action(self) -> Optional[str]:
        """送礼弹窗此刻起来了没有，起来了是哪一个动作按钮。

        「赠送」与「使用」互斥：商店礼物点前者，背包道具点后者，而旧实现正是靠
        `wait_for_any_element(['give_gift', 'use_item'])` 判断弹窗到没到位。

        Returns:
            `GIFT_ACTION_GIVE` / `GIFT_ACTION_USE` 之一；弹窗没出现或超时返回 None。
        """

    @abstractmethod
    async def read_gift_item_name(self) -> Optional[str]:
        """读弹窗里当前选中礼物的**显示名**。

        「显示名」是指已经去掉件数后缀的那个名字：`高级福袋x2` 读回来是 `高级福袋`。
        拆分留在这里是因为「名字后面跟着一个 x 和件数」是 App 的文案格式，而这份显示名
        会原样进入聊天气泡里的「XX 送你啦」，由引擎再拼一次就会在两处各留一份格式知识。

        Returns:
            读不到（背包里没有可用礼物、控件没渲染）返回 None。
        """

    @abstractmethod
    async def read_gift_soul_power(self) -> Optional[str]:
        """读选中礼物旁的灵魂力读数（如 `+12灵魂力`），只进日志。

        读不到返回 None 而不是 `'0'`：兜底的 `'0'` 是旧实现拼日志时用的字面量，留在
        引擎里拼日志才是它的原处，端口不必替调用方编一个读数。
        """

    @abstractmethod
    async def click_gift_item(self) -> bool:
        """点弹窗里当前选中的礼物本身。

        小黄鸭（背包为空时的兜底礼物）点一下即送出，不再需要「赠送」那一步，所以它
        与 `click_gift_action` 是两个手势而不是带开关的一个。
        """

    @abstractmethod
    async def click_gift_action(self) -> bool:
        """点弹窗上此刻存在的那个动作按钮（赠送或使用）。

        不收参数：按钮是哪一个由 `gift_popup_action` 报给引擎，这里只负责点当下那个 ——
        让引擎回传一个元素 key 再点它，等于把 App 的控件词汇泄进引擎层。
        """

    @abstractmethod
    async def confirm_gift_use(self) -> bool:
        """等「使用」之后那道确认框出现并点掉「确认」。"""

    @abstractmethod
    async def dismiss_gift_popup(self) -> bool:
        """把还盖在资料卡上的送礼弹窗收掉，点的是 `GIFT_POPUP_CLOSE_KEYS` 里的页内 X。

        弹窗本来就没开着时直接返回 True（幂等）：「没有弹窗」与「收好了」是同一件事，
        调用方不必先问一遍。收不掉就返回 False 让**调用方**记警告 —— 这里同样没有第二条
        兜底手势，见模块开头的「为什么这个端口里没有 press_back」。
        """

    # ------------------------------------------------------------------
    # 房管（#439）
    # ------------------------------------------------------------------

    @abstractmethod
    async def read_admin_invite_label(self) -> Optional[str]:
        """读资料卡上房管开关此刻写的文案（`ADMIN_LABEL_INVITE` / `ADMIN_LABEL_DISMISS`）。

        「这个人现在是不是房管」这个判断由**调用方**拿着文案去做：把它折成布尔值塞进
        端口，就等于让 App 的控件词汇替聊天命令决定「已经 / 还不是管理员」那句话说给谁
        听，而那正是 #426 里决策该待的地方。

        等待放在这一侧而不是「点」那一侧：旧实现在这里就是一次
        `wait_for_element_clickable('manager_invite')`，读不到正是「没有这枚按钮」那条
        失败路径，读到之后那一次点击不必再等一遍。

        Returns:
            开关上的原文；卡片上根本没有这枚控件返回 None。
        """

    @abstractmethod
    async def click_admin_invite(self) -> bool:
        """点资料卡上的房管开关（邀请与解除管理是同一枚控件）。

        不负责判断该不该点：那是调用方读完文案之后的决定。这里只负责把「点下去」这件
        物理动作做完，并如实回报点没点着。

        Returns:
            点到了返回 True；控件不在页面上、或点击抛错返回 False。
        """

    @abstractmethod
    async def confirm_admin_action(self, action: str) -> bool:
        """等确认框出来并点掉它里面对应 `action` 的按钮。

        Args:
            action: `ADMIN_ACTION_INVITE` 或 `ADMIN_ACTION_DISMISS`。传动作而不是传元素
                key：调用方知道自己要邀请还是要解除，而「这个动作对应哪个控件」是 App
                的词汇，留在适配器里（`ADMIN_CONFIRM_KEYS`）。

        Returns:
            点到了返回 True；确认框没弹出来、或按钮点不到返回 False，让调用方报出
            「没找到确认按钮」—— 旧实现里这正是那一步失败时的原话。
        """

    @abstractmethod
    async def dismiss_admin_confirm(self) -> bool:
        """把可能悬着的房管确认框收掉，按 `ADMIN_CONFIRM_CLOSE_KEYS` 的顺序试完为止。

        幂等：确认框本来就没开着时直接返回 True（「没有弹窗」与「收好了」是同一件事）。
        收不掉返回 False 让**调用方**记警告并保持原状 —— 这里同样没有盲按返回兜底，见
        模块开头的「为什么这个端口里没有 press_back」：旧实现在这两条幂等分支上正是用
        `key_actions.press_back()` 收场，而它会误退出派对房间（spec #426 问题陈述 #1）。
        """

