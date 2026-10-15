"""播放页进入仪式 —— UI 适配器之间的共享前置动作。

「现在到底在不在播放页」这件事，播放模式切换（#423）、伴奏（#427）、歌词（#430）
问的都是同一句，因此这段 UI 前置动作只写一遍，放在端口之外但仍在适配器层：

    ensure_player_page(handler)  →  PlayerPageEntry(ok, element_key, mode_key, element, error)

它只做三件事：把 QQ Music 拉到前台、在底部播放条与播放页模式按钮之间认出所在、
必要时点进播放页。认出「没有音乐在放」也算一种正常结局（`ok=False` + 本地化
错误），调用方据此回复用户即可，不必再自己兜一遍超时与异常。认出的是哪一个元素
（`element_key`）也一并交出来：播放模式据此读出模式 key，伴奏据此分清走的是
「页上直接开关」还是「更多」菜单那条路。

元素 key 全部来自 `config.yaml` 的 `qq_music.elements`（唯一权威），本模块
只出现 key、不出现 XPath。复用方拿到 `PlayerPageEntry.element` 后即可继续点
模式按钮，无需重新探测页面。

「站在播放页上」的证据并不是模式按钮本身 —— 伴奏（#427）认的是伴唱开关或
「更多」入口，歌词（#430）认的又是别的东西。因此这段仪式把那份证据交给调用方
用 `on_page_keys` 指进来，前置动作（切前台、返回、找播放条、必要时点进去）始终
只有这一份。同理，「没有音乐在放」这句话各命令措辞不同，由 `no_music_error`
带进来，仪式本身不替用户决定怎么措辞。
"""

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ushareiplay.managers.playback.models import NO_PLAYING_MUSIC_ERROR

# 模式 key → 播放页上的模式按钮（config.yaml: qq_music.elements）。
PLAY_MODE_ELEMENT_KEYS = {
    "list": "play_mode_list",
    "single": "play_mode_single",
    "random": "play_mode_random",
}

# 伴奏（#427）用来认出「已经在播放页上」的元素：播放页上直接显示的伴唱状态
# 文案，或者需要再点开的「更多」入口。两种并存说明这一版 App 已经激活过伴唱。
ACCOMPANIMENT_TEXT_ON_KEY = "accompaniment_text_on"
ACCOMPANIMENT_TEXT_OFF_KEY = "accompaniment_text_off"
ACCOMPANIMENT_MORE_ENTRY_KEY = "more_entry"
ACCOMPANIMENT_ON_PAGE_KEYS = (
    ACCOMPANIMENT_TEXT_OFF_KEY,
    ACCOMPANIMENT_TEXT_ON_KEY,
    ACCOMPANIMENT_MORE_ENTRY_KEY,
)

# 「更多」菜单那条通路上的其余元素 key（config.yaml: qq_music.elements）。同样放在
# 这里，是因为伴唱开关的 key 词汇表应该只有一份：生产驱动（#421）按 key 取元素，
# 测试按同一份 key 断言，谁都不必自己再抄一遍字符串。
#
# `accompaniment_switch` 是 K歌入口本身（灰掉说明伴奏模式压根没被激活）；
# `accompaniment_menu` 是滚动容器里那个菜单项，`menu_container` 是承载它的列表；
# 最后两个是菜单打开后亮着「伴唱已开启 / 已关闭」的那枚状态按钮。
ACCOMPANIMENT_SWITCH_KEY = "accompaniment_switch"
ACCOMPANIMENT_MENU_KEY = "accompaniment_menu"
ACCOMPANIMENT_MENU_CONTAINER_KEY = "menu_container"
ACCOMPANIMENT_STATE_KEYS = ("accompaniment_button_on", "accompaniment_button_off")

# 探测「在不在播放页」的元素 key：底部播放条说明有音乐但不在播放页，
# 模式按钮说明已经在播放页。一个都找不到就是没有音乐在放。
PLAYER_PAGE_PROBE_KEYS = ("playing_bar",) + tuple(PLAY_MODE_ELEMENT_KEYS.values())

# 元素 key → 模式 key（play_mode_list → list …）。
_MODE_KEY_BY_ELEMENT_KEY = {
    element_key: mode_key for mode_key, element_key in PLAY_MODE_ELEMENT_KEYS.items()
}


@dataclass
class PlayerPageEntry:
    """播放页进入仪式的结果。

    Attributes:
        ok: 是否已经站在播放页上、且当前模式按钮可用。
        element_key: 认出「已经在播放页上」的那个元素 key。调用方靠它决定接下来
            走哪条分支 —— 播放模式用 `mode_key` 就够，但伴奏要分清是页上直接有
            开关还是得再进「更多」菜单（#427）。`ok=False` 时为 None。
        mode_key: 观察到的当前模式 key；`ok=False` 时可能是 `unknown`。
        element: 当前模式按钮元素，供调用方接着点击切换；`ok=False` 时为 None。
        error: 失败原因（本地化），仅 `ok=False` 时有意义。
    """

    ok: bool
    element_key: Optional[str] = None
    mode_key: str = "unknown"
    element: Any = None
    error: Optional[str] = None


def ensure_player_page(
    handler,
    logger=None,
    *,
    on_page_keys: Optional[Sequence[str]] = None,
    no_music_error: Optional[str] = None,
) -> PlayerPageEntry:
    """确保站在 QQ Music 播放页上，并交出调用方要认的那个控件。

    Args:
        handler: `QQMusicHandler`（或其替身）。只需要 `key_actions`、
            `element_finder`、`gesture_handler` 三个协作者。
        logger: 可选的日志器，缺省用 `handler.logger`。只在仪式自己改变了页面时
            记日志（探不到控件说明没在放歌、点播放条进播放页）。而「已经站在播放页
            上」这一路不记：`press_back()` 虽然每次都按，但它没有可观察的结果 ——
            按对了我们看不出区别，按错了下一行的探测会接手 —— 补一条 INFO 只会
            让每次 `:mode` / `:acc` 都多一行无行为触发的日志。
        on_page_keys: 认出「已经在播放页上」的元素 key。缺省是模式按钮（#423 的
            行为）；伴奏传 `ACCOMPANIMENT_ON_PAGE_KEYS`。
        no_music_error: 一个都探不到时回给用户的话。缺省是播放模式那句。

    Returns:
        `PlayerPageEntry` —— 成功时带上 element key、模式 key 与按钮元素；失败时
        带上本地化原因。
    """
    logger = logger if logger is not None else getattr(handler, "logger", None)

    page_keys = tuple(on_page_keys) if on_page_keys else tuple(PLAY_MODE_ELEMENT_KEYS.values())
    no_music_error = no_music_error or NO_PLAYING_MUSIC_ERROR
    # 不指定 `on_page_keys` 时，「在不在播放页」的那份清单就是 `PLAYER_PAGE_PROBE_KEYS`
    # 本身，不再另拼一份等价的列表（两份清单一旦各自演进就会各说各话）。
    probe_keys = (
        PLAYER_PAGE_PROBE_KEYS if not on_page_keys else ("playing_bar",) + page_keys
    )

    if not handler.key_actions.switch_to_app():
        if logger:
            logger.info("无法切换到音乐App")
        return PlayerPageEntry(ok=False, error="无法切换到音乐App，稍后重试")

    # 返回键是无条件的一次导航：可能正停在搜索结果页上，退一步才是播放页。
    handler.key_actions.press_back()

    found_key, found_element = handler.element_finder.wait_for_any_element(list(probe_keys))
    if not found_key or not found_element:
        if logger:
            logger.info("未找到播放模式相关元素，说明现在没有播放音乐")
        return PlayerPageEntry(ok=False, error=no_music_error)

    if found_key == "playing_bar":
        if logger:
            logger.info("找到 playing_bar，点击进入播放页")
        if not handler.gesture_handler.click_element_at(found_element):
            return PlayerPageEntry(ok=False, error="FAIL: 点击 playing_bar 进入播放页失败")

        found_key, found_element = handler.element_finder.wait_for_any_element(list(page_keys))
        if not found_key or not found_element:
            return PlayerPageEntry(
                ok=False, error="FAIL: 点击 playing_bar 后仍未找到播放模式控制元素"
            )

    return PlayerPageEntry(
        ok=True,
        element_key=found_key,
        mode_key=_MODE_KEY_BY_ELEMENT_KEY.get(found_key, "unknown"),
        element=found_element,
    )
