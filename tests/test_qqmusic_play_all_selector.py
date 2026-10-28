"""「播放全部」按钮的选择器必须与真机页面一致。

背景：QQ Music 的歌单详情页把「播放全部」渲染成一个 `content-desc="播放"` 的
FrameLayout，而专辑详情页与收藏页用的是 TextView 文案「全部播放」。两种形态
各占一套 XPath，任何一边缺了都会让对应的播放命令整条失败（线上那次就是
`:playlist` 在歌单详情页上找不到播放按钮）。

这里的夹具是真机 page_source 快照（tests/fixtures/qqmusic_dom/），测试用**生产
的** config.yaml 选择器与**生产的**兜底链 `PLAY_ALL_KEYS` 去匹配它们：
不仅要认得出按钮，还得认的是链上第一个命中的那个 —— 认错按钮比认不出更糟。
"""

from pathlib import Path

import yaml
from lxml import etree

from ushareiplay.managers.playback.qq_music_ui_driver import PLAY_ALL_KEYS

REPO_ROOT = Path(__file__).resolve().parent.parent
DOM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "qqmusic_dom"

# 真机 page_source 快照里「播放全部」按钮的特征（resource-id 是 QQ Music
# 混淆后的 id，随版本变；文案与 content-desc 才是形态本身）。
PLAYLIST_DETAIL_PLAY_ALL = {
    "resource-id": "com.tencent.qqmusic:id/fi2",
    "content-desc": "播放",
}
TEXT_PLAY_ALL = {"text": "全部播放"}


def _qq_music_elements() -> dict:
    with open(REPO_ROOT / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["qq_music"]["elements"]


def _load(page: str) -> etree._Element:
    return etree.parse(str(DOM_FIXTURES / page)).getroot()


def _resolve_play_all(root: etree._Element, elements: dict):
    """按生产兜底链认按钮：第一个命中的 key 胜出（与 `wait_for_any_element` 同口径）。"""
    for key in PLAY_ALL_KEYS:
        matches = root.xpath(elements[key])
        if matches:
            return key, matches[0]
    return None, None


def test_every_play_all_key_is_declared_in_config():
    """兜底链上的每个 key 都得在 config.yaml 里有选择器，否则那一条兜底是死的。"""
    elements = _qq_music_elements()
    missing = [key for key in PLAY_ALL_KEYS if key not in elements]
    assert missing == []


def test_playlist_detail_page_exposes_the_play_all_button():
    """歌单详情页：认得出的必须是那个 FrameLayout「播放」。

    这正是线上那次的现场：三种旧形态在这一页一个都不认，于是
    `wait_for_any_element` 超时，`:playlist` 整条命令失败。
    """
    elements = _qq_music_elements()
    root = _load("playlist_detail.xml")

    key, element = _resolve_play_all(root, elements)

    assert key is not None, "歌单详情页认不出「播放全部」按钮"
    assert element.get("resource-id") == PLAYLIST_DETAIL_PLAY_ALL["resource-id"]
    assert element.get("content-desc") == PLAYLIST_DETAIL_PLAY_ALL["content-desc"]
    # 点击落在按钮自身：FrameLayout 自己可点，不是靠子控件兜。
    assert element.get("clickable") == "true"
    assert element.get("enabled") == "true"


def test_album_detail_page_still_resolves_to_the_text_button():
    """专辑详情页：兜底链仍须先认出 TextView「全部播放」，不能被别的形态抢走。"""
    elements = _qq_music_elements()
    root = _load("album_detail.xml")

    key, element = _resolve_play_all(root, elements)

    assert key == "play_all"
    assert element.get("text") == TEXT_PLAY_ALL["text"]


def test_favourites_page_still_resolves_to_the_text_button():
    """收藏页：认的是顶部那栏的「全部播放」。

    「我的」页的行内播放按钮也是 `content-desc="播放"`，但它们不是 FrameLayout；
    兜底链认错行内按钮就会只放一首 —— 因此这里盯住命中的 key 与文案。
    """
    elements = _qq_music_elements()
    root = _load("favourites.xml")

    key, element = _resolve_play_all(root, elements)

    assert key == "play_all"
    assert element.get("text") == TEXT_PLAY_ALL["text"]
