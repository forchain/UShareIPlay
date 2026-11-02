"""抽屉行编辑器：话题 / 公告 / 房名三条纵切合成的**同一个** ritual（#489）。

原先抽屉里的三行各写了一遍「打开编辑层 → 写入 → 提交 → 判结果 → 收尾」，
三份拷贝各自漂移：同一个「别人房间」在三条路上叫三个名字、同一个「改得太
频繁」是两句不同的话、公告那条路干脆没有「被拒」这一档。现在那一段收成了
抽屉行编辑器（`row_editor`），三行各自只剩**一条**皮肤常量。

本文件考的是编辑器这一层，入口仍然是 `RoomProfileManager` 的公开方法 + 内存
抽屉驱动（不 mock 内部实现，因此不需要 Android 或 Appium）：

- 别人房间里三个字段的观感完全一样：一个点击都不发生，草稿与预算都不动；
- 提交被拒（改得太频繁）时编辑层被收掉，草稿留着，本字段的时钟推进，
  **别的**字段的预算不受影响；公告那条路没有「被拒」这一档；
- 缺哪一个控件就报哪一个既有的报错文案，草稿留着；
- 记账次序：跳过从不推进时钟，别的结局恰好推进一次；
- 第四个抽屉字段 = 一条常量，不必再抄一遍 ritual。

三个字段既有的那三个测试文件（`test_room_profile_topic.py` /
`_notice.py` / `_title.py`）在它们自己的接缝上继续逐字不变地通过 ——
本文件只补「三行合一行之后才成立」的那些断言。
"""

import ast
import pathlib
from unittest.mock import MagicMock

import pytest

from ushareiplay.managers.room_profile import RoomProfileManager
from ushareiplay.managers.room_profile.row_editor import (
    RowSkin,
    RowStep,
    WriteOutcome,
)
from ushareiplay.state.room_state import RoomState
from tests.fakes.in_memory_room_profile_drawer import InMemoryRoomProfileDrawerDriver

PKG = pathlib.Path(__file__).resolve().parents[1] / 'src/ushareiplay/managers/room_profile'

FULLWIDTH_SEPARATOR = '｜'
DEFAULT_THEME = '听歌'
DEFAULT_TITLE = '听歌'
DEFAULT_NOTICE = 'U Share I Play\n分享音乐 享受快乐'

CONFIG = {
    'default_theme': DEFAULT_THEME,
    'default_title': DEFAULT_TITLE,
    'default_notice': DEFAULT_NOTICE,
    'system_default_notices': ['弹唱大会', 'Souler们在随便聊聊ing', '蹲一个人'],
}

#: 每一行抽屉在「编辑层弹出」时的屏幕。
SCREENS = {
    'topic': {
        'present': ('edit_topic_entry', 'edit_topic_input', 'edit_topic_confirm'),
        'world_after_click': {'edit_topic_confirm': ('input_box_entry',)},
    },
    'notice': {
        'present': (
            'edit_notice_entry',
            'close_notice',
            'customize_notice_button',
            'edit_notice_input',
            'edit_notice_confirm',
        ),
    },
    'title': {
        'present': (
            'slide_drawer',
            'title_edit_entry',
            'title_edit_input',
            'title_edit_confirm',
        ),
        'world_after_click': {'title_edit_confirm': ('slide_drawer', 'title_edit_entry')},
    },
}

#: 三个字段在别人房间里的对外形状（**逐字冻结**：历史上就长得不一样）。
GUEST_SKIP_RESULTS = {
    'topic': {'skipped': 'guest_room'},
    'notice': {'skipped': True, 'reason': 'guest_room'},
    'title': {'skipped': True, 'reason': 'guest_room'},
}

FIELDS = ('topic', 'notice', 'title')


@pytest.fixture(autouse=True)
def reset_singletons():
    RoomProfileManager.reset_instance()
    RoomState.reset_instance()
    yield
    RoomProfileManager.reset_instance()
    RoomState.reset_instance()


class _RoomTextFinder:
    """判定读（房名 / 公告），与 `test_room_profile_title.py` 同一个形状。"""

    def __init__(self, room_title_text='听歌｜晚安', notice_text=''):
        self.room_title_text = room_title_text
        self.notice_text = notice_text
        self.room_title_element = object()
        self.notice_element = object()

    def wait_for_element(self, key, timeout=10):
        return {
            'room_name_in_dialog': self.room_title_element,
            'chat_room_notice': self.notice_element,
        }.get(key)

    def try_find_element(self, key, log=False):
        return self.wait_for_element(key)

    def get_element_text(self, element):
        if element is self.notice_element:
            return self.notice_text
        return self.room_title_text


class _Handler:
    """话题只需要切前台；房名还要那两次判定读。"""

    def __init__(self, room_title_text='听歌｜晚安', notice_text=''):
        self.logger = MagicMock()
        self.key_actions = MagicMock()
        self.key_actions.switch_to_app.return_value = True
        self.element_finder = _RoomTextFinder(room_title_text, notice_text)
        self.config = CONFIG

    def log_error(self, _message):
        return None


def _profile(driver=None, handler=None):
    profile = RoomProfileManager.initialize(
        handler=handler or _Handler(), drawer_driver=driver
    )
    # 确认提交后的静默等待是真实 Appium 时序，离线测试直接跳过。
    profile.topic_settle_seconds = 0
    profile.title_settle_seconds = 0
    return profile


def _driver(field='topic', **kwargs):
    kwargs.setdefault('present', SCREENS[field]['present'])
    kwargs.setdefault('world_after_click', SCREENS[field].get('world_after_click'))
    return InMemoryRoomProfileDrawerDriver(**kwargs)


def _queue(profile, field, text):
    """排队一条草稿（三个字段的排队入口各不相同）。"""
    if field == 'topic':
        profile.set_topic(text)
    elif field == 'notice':
        profile.set_notice(text)
    else:
        profile.set_title(text)


def _flush(profile, field):
    """心跳：把排队的草稿写出去。"""
    return getattr(profile, f'update_{field}')()


def _guest_room():
    """把房间状态临时切成「在别人的房间里」。"""
    room_state = RoomState.initialize()
    room_state.is_guest_room = True
    return room_state


# --------------------------------------------------------------------------
# 别人房间：三个字段的观感完全一样
# --------------------------------------------------------------------------


@pytest.mark.parametrize('field', FIELDS)
def test_a_guest_room_skips_every_row_the_same_way(field):
    """别人房间里一个点击都不发生：草稿留着、预算留着、公屏不播报。"""
    driver = _driver(field)
    profile = _profile(driver)

    # 先在自家房间排队，再切到别人的房间 —— 排队的变更必须原地等着。
    _queue(profile, field, '夜曲')
    assert profile.drafts.last_attempt_at(field) is None

    _guest_room()
    result = _flush(profile, field)

    assert result == GUEST_SKIP_RESULTS[field]
    assert driver.opened_entries == [], '别人房间里不许开抽屉'
    assert driver.clicks == [], '别人房间里一次点击都不该有'
    assert driver.typed == []
    assert profile.drafts.pending(field) == '夜曲', '跳过不是清空'
    assert profile.drafts.last_attempt_at(field) is None, '跳过不能烧冷却预算'
    assert profile.drafts.can_apply_now(field) is True


@pytest.mark.parametrize('field', FIELDS)
def test_a_guest_room_skip_keeps_the_other_fields_budgets_intact(field):
    """跳过一个字段不许动别的字段的预算（ADR-0001 的独立预算）。"""
    driver = _driver(field)
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    _guest_room()
    _flush(profile, field)

    for other in FIELDS:
        if other == field:
            continue
        assert profile.drafts.last_attempt_at(other) is None
        assert profile.drafts.can_apply_now(other) is True


# --------------------------------------------------------------------------
# 提交被拒：编辑层必须收掉
# --------------------------------------------------------------------------

#: 提交之后编辑层还在（风险提示盖住主界面）= 改得太频繁。
CONFLICT_SCREENS = {
    'topic': {
        'present': ('edit_topic_entry', 'edit_topic_input', 'edit_topic_confirm'),
        'world_after_click': {'edit_topic_confirm': ('edit_topic_confirm',)},
    },
    'title': {
        'present': (
            'slide_drawer',
            'title_edit_entry',
            'title_edit_input',
            'title_edit_confirm',
            'go_back',
        ),
        'world_after_click': {
            'title_edit_confirm': (
                'slide_drawer',
                'title_edit_input',
                'title_edit_confirm',
                'go_back',
            )
        },
    },
}

CONFLICT_ERRORS = {
    'topic': 'update topic too frequently',
    'title': 'Update failed - still in cooldown period',
}


@pytest.mark.parametrize('field', ('topic', 'title'))
def test_a_conflict_keeps_the_draft_and_advances_only_that_field_s_clock(field):
    driver = _driver(field, **CONFLICT_SCREENS[field])
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    result = _flush(profile, field)

    assert result == {'error': CONFLICT_ERRORS[field]}
    assert profile.drafts.pending(field) == '夜曲', '被拒也要留着草稿等下个冷却'
    assert profile.drafts.last_attempt_at(field) is not None, '被拒也算一次尝试'
    for other in FIELDS:
        if other != field:
            assert profile.drafts.last_attempt_at(other) is None, '别的字段的预算不受影响'


@pytest.mark.parametrize('field', ('topic', 'title'))
def test_a_conflict_never_leaves_the_edit_layer_on_screen(field):
    """提交被拒时编辑层还开着：它必须被收掉，不能留在用户的屏幕上。"""
    driver = _driver(field, **CONFLICT_SCREENS[field])
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    _flush(profile, field)

    if field == 'title':
        # 房名那一行还要把公告补回去，抽屉会话得留着，因此显式收掉编辑层。
        assert 'go_back' in driver.clicks, '编辑层没收起来'
    else:
        # 话题那一行没有自己的收尾按钮：编辑层由抽屉会话自己的收尾阶梯带走。
        assert driver.close_attempts == 1, '抽屉会话要把它自己打开的那次收掉'
    assert driver.back_presses == 0, '不得盲按返回键'


def test_the_notice_row_has_no_conflict_probe_at_all():
    """公告那条路没有「被拒」这一档：点完确认就收尾（既有行为）。"""
    driver = _driver(
        'notice',
        world_after_click={'edit_notice_confirm': ('edit_notice_confirm',)},
    )
    profile = _profile(driver)
    profile.set_notice('今晚八点开播')

    result = profile.update_notice()

    assert result == {'success': 'Notice restored to: 今晚八点开播'}
    assert profile.drafts.pending('notice') is None


# --------------------------------------------------------------------------
# 找不到控件：报各自的既有文案，草稿留着
# --------------------------------------------------------------------------

MISSING_CONTROL_CASES = (
    ('topic', ('edit_topic_input', 'edit_topic_confirm'), 'Failed to find edit topic entry'),
    ('topic', ('edit_topic_entry', 'edit_topic_confirm'), 'Failed to find topic input'),
    ('topic', ('edit_topic_entry', 'edit_topic_input'), 'Failed to find confirm button'),
    (
        'title',
        ('slide_drawer', 'title_edit_input', 'title_edit_confirm'),
        'Failed to find edit title entry',
    ),
    (
        'title',
        ('slide_drawer', 'title_edit_entry', 'title_edit_confirm'),
        'Failed to find title input',
    ),
    (
        'title',
        ('slide_drawer', 'title_edit_entry', 'title_edit_input'),
        'Failed to find confirm button',
    ),
    ('notice', ('close_notice',), 'Failed to find edit notice entry'),
    ('notice', ('edit_notice_entry',), 'Close notice not found'),
    (
        'notice',
        ('edit_notice_entry', 'close_notice'),
        'Failed to find customize notice button',
    ),
    (
        'notice',
        ('edit_notice_entry', 'close_notice', 'customize_notice_button'),
        'Failed to find notice input',
    ),
    (
        'notice',
        (
            'edit_notice_entry',
            'close_notice',
            'customize_notice_button',
            'edit_notice_input',
        ),
        'Failed to find confirm button',
    ),
)


@pytest.mark.parametrize('field, present, expected_error', MISSING_CONTROL_CASES)
def test_a_missing_control_reports_its_own_error_and_keeps_the_draft(
    field, present, expected_error
):
    driver = _driver(field, present=present)
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    result = _flush(profile, field)

    assert result == {'error': expected_error}
    assert profile.drafts.pending(field) == '夜曲', '失败要留着草稿等下个冷却'


# --------------------------------------------------------------------------
# 记账次序
# --------------------------------------------------------------------------


@pytest.mark.parametrize('field', FIELDS)
def test_a_skipped_row_never_advances_the_cooldown_clock(field):
    """跳过不是一次尝试：时钟一步都不许动。"""
    driver = _driver(field)
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    calls = []
    original = profile.drafts.mark_attempted
    profile.drafts.mark_attempted = lambda name, now=None: (
        calls.append(name),
        original(name, now),
    )[1]

    _guest_room()
    _flush(profile, field)

    assert calls == [], '跳过不许记账'


@pytest.mark.parametrize('field', FIELDS)
def test_every_other_outcome_advances_the_cooldown_clock_exactly_once(field):
    """写过了（无论成败）恰好记一次账 —— 否则会变成紧循环重试。"""
    driver = _driver(field)
    profile = _profile(driver)
    _queue(profile, field, '夜曲')

    calls = []
    original = profile.drafts.mark_attempted
    profile.drafts.mark_attempted = lambda name, now=None: (
        calls.append(name),
        original(name, now),
    )[1]

    _flush(profile, field)

    assert calls == [field], '一次尝试记一次账'
    assert profile.drafts.last_attempt_at(field) is not None


# --------------------------------------------------------------------------
# 第四个抽屉字段 = 一条常量
# --------------------------------------------------------------------------

#: 假想的第四行（房间标语）。它只是一条常量 —— 没有新的 ritual 代码。
SLOGAN_SKIN = RowSkin(
    field='slogan',
    drawer_entry_keys=('chat_room_title',),
    open_error='Failed to find room slogan',
    entry_steps=(
        RowStep(
            action='click',
            key='edit_slogan_entry',
            error='Failed to find edit slogan entry',
        ),
    ),
    input_key='edit_slogan_input',
    input_error='Failed to find slogan input',
    confirm_key='edit_slogan_confirm',
    confirm_error='Failed to find confirm button',
    probe_keys=('slogan_edit_entry', 'edit_slogan_confirm'),
    probe_outcomes={
        'edit_slogan_confirm': WriteOutcome.CONFLICT,
        'slogan_edit_entry': WriteOutcome.SUCCESS,
    },
    unknown_outcome=WriteOutcome.RENDER_FAILED,
    unknown_error='Failed to update slogan, unknown error',
    conflict_error='Update failed - still in cooldown period',
    conflict_log='Update slogan too frequently, hide edit slogan dialog',
    conflict_close_key='go_back',
    exception_log='Error in slogan update: {traceback}',
    exception_error='Failed to update slogan: {text}',
    no_pending_result={'skipped': 'no pending slogan'},
    cooldown_result=lambda _manager: {'skipped': 'cooldown'},
    to_result=lambda _manager, result: {'success': True, 'error': result.reason},
)


def test_a_fourth_drawer_row_is_a_constant_and_needs_no_new_ritual_code():
    """第四行 = 一条常量：编辑器原样把它写出去。"""
    driver = InMemoryRoomProfileDrawerDriver(
        present=('edit_slogan_entry', 'edit_slogan_input', 'edit_slogan_confirm',
                 'slogan_edit_entry', 'go_back'),
        world_after_click={'edit_slogan_confirm': ('slogan_edit_entry',)},
    )
    profile = _profile(driver)

    outcome = profile._row_editor().edit_row(SLOGAN_SKIN, '今天也要开心')

    assert outcome.outcome is WriteOutcome.SUCCESS
    assert driver.typed == [('edit_slogan_input', '今天也要开心')]
    assert driver.opened_entries == ['chat_room_title']
    assert driver.close_attempts == 1


def test_a_fourth_row_reports_a_conflict_with_its_own_words():
    driver = InMemoryRoomProfileDrawerDriver(
        present=('edit_slogan_entry', 'edit_slogan_input', 'edit_slogan_confirm',
                 'go_back'),
        world_after_click={'edit_slogan_confirm': ('edit_slogan_confirm', 'go_back')},
    )
    profile = _profile(driver)

    outcome = profile._row_editor().edit_row(SLOGAN_SKIN, '今天也要开心')

    assert outcome.outcome is WriteOutcome.CONFLICT
    assert outcome.reason == 'Update failed - still in cooldown period'
    assert 'go_back' in driver.clicks, '被拒时编辑层要被收掉'


# --------------------------------------------------------------------------
# 结局类型与探测键：表驱动，离线就能抓到手误
# --------------------------------------------------------------------------


def test_the_outcome_type_has_exactly_the_four_kinds():
    assert {outcome.name for outcome in WriteOutcome} == {
        'SUCCESS',
        'CONFLICT',
        'RENDER_FAILED',
        'SKIPPED',
    }


@pytest.mark.parametrize(
    'skin, probe_keys',
    [
        ('TOPIC_SKIN', ('input_box_entry', 'edit_topic_confirm')),
        ('NOTICE_SKIN', ()),
        ('TITLE_SKIN', ('title_edit_entry', 'title_edit_confirm')),
    ],
)
def test_every_skin_declares_its_probe_keys_and_what_each_of_them_means(skin, probe_keys):
    """探测键集合与判定表都在皮肤里 —— 写错一个 key 在这里就能抓到。"""
    from ushareiplay.managers.room_profile import manager as manager_module

    row_skin = getattr(manager_module, skin)

    assert row_skin.probe_keys == probe_keys
    for key in row_skin.probe_keys:
        assert key in row_skin.probe_outcomes, f'{skin} 的探测键 {key} 没有判定'
        assert isinstance(row_skin.probe_outcomes[key], WriteOutcome)
    assert isinstance(row_skin.unknown_outcome, WriteOutcome)


# --------------------------------------------------------------------------
# 收口契约：ritual 只有一份，守卫只有一处
# --------------------------------------------------------------------------

#: 写 UI 的那些函数：它们不许再各自抄一份 ritual 或守卫。
_ROW_WRITE_FUNCTIONS = {
    'update_topic',
    'update_notice',
    'update_title',
    'restore_notice',
    '_flush_row',
    '_edit_row',
    '_write_topic_in_drawer',
    '_write_notice_in_drawer',
    '_write_title_in_drawer',
}

#: 抽屉的物理原语：只允许出现在抽屉行编辑器里。
_PHYSICAL_PRIMITIVES = {'replace_text', 'click_element', 'click_element_at', 'wait_for_any'}


def _manager_source() -> str:
    return (PKG / 'manager.py').read_text(encoding='utf-8')


def test_the_physical_ritual_lives_only_in_the_row_editor():
    """「等入口 → 写输入框 → 确认 → 判结果」只允许有一份。"""
    tree = ast.parse(_manager_source())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in _ROW_WRITE_FUNCTIONS:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and sub.attr in _PHYSICAL_PRIMITIVES:
                offenders.append(f'{node.name}: {sub.attr}')
    assert offenders == [], f'ritual 被抄进了这些函数：{offenders}'


def test_the_guest_room_guard_for_drawer_edits_is_defined_in_exactly_one_place():
    """「什么算别人的房间」只有一个定义：改判定不会漏掉某一条路。"""
    editor_source = (PKG / 'row_editor.py').read_text(encoding='utf-8')
    assert editor_source.count('RoomState.in_guest_room()') == 1

    tree = ast.parse(_manager_source())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in _ROW_WRITE_FUNCTIONS:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and sub.attr == 'in_guest_room':
                offenders.append(node.name)
    assert offenders == [], f'这些函数各自抄了一份守卫：{offenders}'
