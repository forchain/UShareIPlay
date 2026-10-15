"""播放页进入仪式 —— UI 适配器之间的共享前置动作。

「现在到底在不在播放页」这件事，播放模式切换（#423）、伴奏（#427）、歌词（#430）
问的都是同一句，因此这段 UI 前置动作只写一遍，放在端口之外但仍在适配器层：

    ensure_player_page(handler)  →  PlayerPageEntry(ok, mode_key, element, error)

它只做三件事：把 QQ Music 拉到前台、在底部播放条与播放页模式按钮之间认出所在、
必要时点进播放页。认出「没有音乐在放」也算一种正常结局（`ok=False` + 本地化
错误），调用方据此回复用户即可，不必再自己兜一遍超时与异常。

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
ACCOMPANIMENT_ON_PAGE_KEYS = (
    "accompaniment_text_off",
    "accompaniment_text_on",
    "more_entry",
)

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
        mode_key: 观察到的当前模式 key；`ok=False` 时可能是 `unknown`。
        element: 当前模式按钮元素，供调用方接着点击切换；`ok=False` 时为 None。
        error: 失败原因（本地化），仅 `ok=False` 时有意义。
    """

    ok: bool
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
        logger: 可选的日志器，缺省用 `handler.logger`。只在真的发生动作时记日志 ——
            已经站在播放页上是一次空转，不该留下日志。
        on_page_keys: 认出「已经在播放页上」的元素 key。缺省是模式按钮（#423 的
            行为）；伴奏传 `ACCOMPANIMENT_ON_PAGE_KEYS`。
        no_music_error: 一个都探不到时回给用户的话。缺省是播放模式那句。

    Returns:
        `PlayerPageEntry` —— 成功时带上模式 key 与按钮元素；失败时带上本地化原因。
    """
    logger = logger if logger is not None else getattr(handler, "logger", None)

    page_keys = tuple(on_page_keys) if on_page_keys else tuple(PLAY_MODE_ELEMENT_KEYS.values())
    no_music_error = no_music_error or NO_PLAYING_MUSIC_ERROR

    if not handler.key_actions.switch_to_app():
        if logger:
            logger.info("无法切换到音乐App")
        return PlayerPageEntry(ok=False, error="无法切换到音乐App，稍后重试")

    handler.key_actions.press_back()

    found_key, found_element = handler.element_finder.wait_for_any_element(
        list(("playing_bar",) + page_keys)
    )
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
        mode_key=_MODE_KEY_BY_ELEMENT_KEY.get(found_key, "unknown"),
        element=found_element,
    )
