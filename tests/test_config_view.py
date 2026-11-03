"""配置视图与选择器值对象的语义（ADR-0012）。

配置读取只有一个入口：根配置用 `ConfigView`，应用段用 `ConfigSectionView`，
UI 选择器用 `Locator`。这里盯住三件事：

- 选择器字符串怎么被判定成 XPath 还是 resource-id，以及派生出的定位元组与 XPath；
- 视图不是字典：没有 `view[...]`，也没有 `view.get(...)`；
- 热重载原地改写底层映射，视图与段视图的对象身份不变。
"""

import re
import xml.etree.ElementTree as ET

import pytest
from appium.webdriver.common.appiumby import AppiumBy

from ushareiplay.core.config_view import (
    ConfigError,
    ConfigSectionView,
    ConfigView,
    Locator,
    MissingConfigKey,
    MissingConfigSection,
    MissingElementKey,
)

# ---------------------------------------------------------------------------
# XPath 求值：Locator.matches 走的是 lxml 的 getroottree()/getpath()/xpath()。
# 这里用 xml.etree.ElementTree 实现同一套调用，测试因此不依赖 lxml。
# ---------------------------------------------------------------------------

_XPATH_PATTERN = re.compile(
    r"^(?:\.|//)*"
    r"(?P<tag>[^\[@]+)?"
    r"(?:\[@(?P<attr>[\w.\-]+)=(?P<quote>['\"])(?P<value>[^'\"]*)(?P=quote)\])?$"
)


class _ElementNode:
    """ElementTree 元素的薄包装：补上 lxml 元素才有的 getroottree()。"""

    def __init__(self, element, document):
        self._element = element
        self._document = document

    @property
    def element(self):
        return self._element

    def get(self, name, default=None):
        return self._element.get(name, default)

    def getroottree(self):
        return self._document

    def __getattr__(self, name):
        return getattr(self._element, name)


class _ElementDocument:
    """xml.etree.ElementTree 版的小型 XPath 求值器（只支持测试用到的写法）。"""

    def __init__(self, root):
        self._root = root
        self._paths = {id(root): "/"}
        self._index(root, "")

    def _index(self, element, prefix):
        counts = {}
        for child in element:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            path = f"{prefix}/{child.tag}[{counts[child.tag]}]"
            self._paths[id(child)] = path
            self._index(child, path)

    def getpath(self, node):
        element = node.element if isinstance(node, _ElementNode) else node
        return self._paths[id(element)]

    def xpath(self, expression):
        match = _XPATH_PATTERN.match(expression.strip())
        if match is None:
            raise ValueError(f"测试替身不支持这条 XPath: {expression}")
        tag = match.group("tag")
        attribute = match.group("attr")
        expected = match.group("value")
        hits = []
        for element in self._root.iter():
            if tag and tag != "*" and element.tag != tag:
                continue
            if attribute is not None and element.get(attribute) != expected:
                continue
            hits.append(_ElementNode(element, self))
        return hits


def _hierarchy():
    """一份极小的界面层级：root 容器 + 回复框 + 正文。"""
    return ET.fromstring(
        '<hierarchy>'
        '<android.widget.FrameLayout resource-id="cn.soulapp.android:id/root"/>'
        '<android.widget.TextView '
        'resource-id="cn.soulapp.android:id/gReplyView" text="回复"/>'
        '<android.widget.TextView '
        'resource-id="cn.soulapp.android:id/tvContent" text="正文"/>'
        '</hierarchy>'
    )


# ---------------------------------------------------------------------------
# Locator：选择器字符串的判定与派生
# ---------------------------------------------------------------------------


def test_from_value_classifies_xpath_and_id_selectors():
    assert Locator.from_value("//android.widget.TextView").kind == "xpath"
    assert Locator.from_value("//android.widget.TextView").value == (
        "//android.widget.TextView"
    )

    assert Locator.from_value("cn.soulapp.android:id/gReplyView").kind == "id"
    assert Locator.from_value("gReplyView").kind == "id"
    assert Locator.from_value("gReplyView").value == "gReplyView"


def test_from_value_strips_surrounding_whitespace():
    locator = Locator.from_value("  //android.widget.TextView  ")

    assert locator.kind == "xpath"
    assert locator.value == "//android.widget.TextView"

    id_locator = Locator.from_value("\tcn.soulapp.android:id/btnSend\n")
    assert id_locator.kind == "id"
    assert id_locator.value == "cn.soulapp.android:id/btnSend"


def test_appium_locator_for_id_and_xpath():
    id_locator = Locator.from_value("cn.soulapp.android:id/gReplyView")
    xpath_locator = Locator.from_value("//android.widget.TextView")

    assert id_locator.appium == (AppiumBy.ID, "cn.soulapp.android:id/gReplyView")
    assert xpath_locator.appium == (AppiumBy.XPATH, "//android.widget.TextView")


def test_absolute_xpath_for_id_and_xpath():
    id_locator = Locator.from_value("cn.soulapp.android:id/gReplyView")
    xpath_locator = Locator.from_value("//android.widget.TextView")

    assert id_locator.absolute_xpath == (
        "//*[@resource-id='cn.soulapp.android:id/gReplyView']"
    )
    assert xpath_locator.absolute_xpath == "//android.widget.TextView"


def test_relative_xpath_for_id_and_xpath():
    id_locator = Locator.from_value("cn.soulapp.android:id/gReplyView")
    xpath_locator = Locator.from_value("//android.widget.TextView")

    assert id_locator.relative_xpath == (
        ".//*[@resource-id='cn.soulapp.android:id/gReplyView']"
    )
    assert xpath_locator.relative_xpath == ".//android.widget.TextView"


def test_relative_xpath_keeps_an_already_relative_xpath():
    # 只有 "//" 开头的字符串才算 XPath，"." 开头的按 resource-id 处理，
    # 因此这一条只能由直接构造的 xpath Locator 走到。
    locator = Locator(kind="xpath", value=".//android.widget.TextView")

    assert locator.relative_xpath == ".//android.widget.TextView"


# ---------------------------------------------------------------------------
# Locator.matches：节点匹配
# ---------------------------------------------------------------------------


def test_matches_bare_resource_id_against_package_qualified_node():
    root = _hierarchy()
    reply_view = root.find(".//android.widget.TextView[@resource-id='cn.soulapp.android:id/gReplyView']")

    assert Locator.from_value("gReplyView").matches(reply_view) is True


def test_matches_package_qualified_resource_id_against_another_node():
    root = _hierarchy()
    content_view = root.find(".//android.widget.TextView[@resource-id='cn.soulapp.android:id/tvContent']")

    assert Locator.from_value("cn.soulapp.android:id/gReplyView").matches(
        content_view
    ) is False


def test_matches_resource_id_without_a_resource_id_attribute():
    root = _hierarchy()
    container = root.find(".//android.widget.FrameLayout")
    container.attrib.pop("resource-id")

    assert Locator.from_value("gReplyView").matches(container) is False


def test_matches_xpath_selector_against_the_selected_node():
    root = _hierarchy()
    document = _ElementDocument(root)
    reply_view = _ElementNode(
        root.find(".//android.widget.TextView[@resource-id='cn.soulapp.android:id/gReplyView']"),
        document,
    )

    locator = Locator.from_value(
        "//android.widget.TextView[@resource-id='cn.soulapp.android:id/gReplyView']"
    )

    assert locator.matches(reply_view) is True


def test_matches_xpath_selector_rejects_a_node_it_does_not_select():
    root = _hierarchy()
    document = _ElementDocument(root)
    content_view = _ElementNode(
        root.find(".//android.widget.TextView[@resource-id='cn.soulapp.android:id/tvContent']"),
        document,
    )

    locator = Locator.from_value(
        "//android.widget.TextView[@resource-id='cn.soulapp.android:id/gReplyView']"
    )

    # 选择器本身是好的：它选中的是另一个节点，不是「什么都没选中」
    hits = document.xpath(locator.value)
    assert len(hits) == 1
    assert document.getpath(hits[0]) != document.getpath(content_view)

    assert locator.matches(content_view) is False


# ---------------------------------------------------------------------------
# ConfigSectionView：段内的选择器与参数
# ---------------------------------------------------------------------------


def test_section_element_returns_a_locator_for_a_known_key():
    section = ConfigSectionView(
        "soul",
        {"elements": {"message_content": "//android.widget.TextView[@text='hi']"}},
    )

    locator = section.element("message_content")

    assert isinstance(locator, Locator)
    assert locator.kind == "xpath"
    assert locator.value == "//android.widget.TextView[@text='hi']"


def test_section_element_raises_with_the_section_and_the_key():
    section = ConfigSectionView("soul", {"elements": {"button_send": "btnSend"}})

    with pytest.raises(MissingElementKey) as excinfo:
        section.element("input_box")

    assert excinfo.value.section == "soul"
    assert excinfo.value.key == "input_box"


def test_section_maybe_element_returns_none_for_an_absent_key():
    section = ConfigSectionView("soul", {"elements": {"button_send": "btnSend"}})

    assert section.maybe_element("input_box") is None


def test_section_value_require_and_maybe_section():
    section = ConfigSectionView(
        "soul",
        {
            "room_owner": "Joyer",
            "elements": {"button_send": "btnSend"},
            "post_party_create": {"enabled": True},
        },
    )

    assert section.value("room_owner") == "Joyer"
    assert section.value("missing", 720) == 720
    assert section.require("room_owner") == "Joyer"

    with pytest.raises(MissingConfigKey) as excinfo:
        section.require("missing")
    assert excinfo.value.section == "soul"
    assert excinfo.value.key == "missing"

    nested = section.maybe_section("post_party_create")
    assert isinstance(nested, ConfigSectionView)
    assert nested.value("enabled") is True
    assert section.maybe_section("nowhere") is None


# ---------------------------------------------------------------------------
# ConfigView：根视图与热重载
# ---------------------------------------------------------------------------


def test_config_view_exposes_sections_and_reports_a_missing_one():
    view = ConfigView({"soul": {"room_owner": "Joyer"}, "qq_music": {}})

    assert view.soul.value("room_owner") == "Joyer"
    assert view.music.value("package_name") is None
    assert view.section("soul") is view.soul
    assert view.maybe_section("nowhere") is None

    with pytest.raises(MissingConfigSection) as excinfo:
        view.section("nowhere")
    assert excinfo.value.section == "nowhere"


def test_reload_keeps_the_view_and_the_section_identity():
    data = {"soul": {"room_owner": "Joyer"}}
    view = ConfigView(data)
    soul = view.soul

    view.reload({"soul": {"room_owner": "Alice"}})

    assert view.soul is soul
    assert soul.value("room_owner") == "Alice"
    assert view.soul.value("room_owner") == "Alice"


def test_reload_mutates_the_wrapped_mapping_in_place():
    data = {"soul": {"room_owner": "Joyer"}, "commands": [{"prefix": "play"}]}
    view = ConfigView(data)
    soul = view.soul

    view.reload({"soul": {"room_owner": "Alice"}, "commands": [{"prefix": "seat"}]})

    assert view.data is data
    assert data["soul"] is soul.data
    assert data["soul"]["room_owner"] == "Alice"
    assert view.command_entries == [{"prefix": "seat"}]


def test_views_are_not_dicts():
    view = ConfigView({"soul": {"room_owner": "Joyer"}})
    section = view.soul

    assert not isinstance(view, dict)
    assert not isinstance(section, dict)

    with pytest.raises(TypeError):
        view["soul"]
    with pytest.raises(TypeError):
        section["room_owner"]

    # 视图根本没有 get 方法：既不是字典，也没有字典那套取值入口
    with pytest.raises(AttributeError):
        view.get("soul")
    with pytest.raises(AttributeError):
        section.get("room_owner")


def test_configuration_errors_share_one_base_class():
    assert issubclass(MissingConfigSection, ConfigError)
    assert issubclass(MissingConfigKey, ConfigError)
    assert issubclass(MissingElementKey, ConfigError)
