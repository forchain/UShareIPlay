from types import SimpleNamespace
from ushareiplay.managers.room_info_auditor import RoomInfoWindowAuditor


class _MockHandler:
    def __init__(self):
        self.logger = SimpleNamespace(
            info=lambda _msg: None,
            warning=lambda _msg: None,
            error=lambda _msg: None
        )
        self.key_actions = SimpleNamespace(press_back=lambda: None)


def test_room_info_auditor_single_pass_execution():
    RoomInfoWindowAuditor.reset_instance()
    auditor = RoomInfoWindowAuditor.initialize()
    auditor._handler = _MockHandler()

    from ushareiplay.managers.recommendation_manager import RecommendationManager
    from ushareiplay.managers.party_manager import PartyManager
    from ushareiplay.managers.room_name_manager import RoomNameManager
    from ushareiplay.managers.notice_manager import NoticeManager

    rm = RecommendationManager._instance if RecommendationManager.is_initialized() else SimpleNamespace()
    rm.inspect_current_ui_status = lambda wait=True: True
    rm.room_state = SimpleNamespace(recommendation_enabled=True)
    RecommendationManager._instance = rm
    RecommendationManager._singleton_initialized = True

    pm = SimpleNamespace(handler=_MockHandler(), sync_and_correct_room_type_if_dialog_open=lambda: {'success': True})
    PartyManager._instance = pm
    PartyManager._singleton_initialized = True

    rnm = SimpleNamespace(handler=_MockHandler(), initialize_from_ui=lambda: {'success': True})
    RoomNameManager._instance = rnm
    RoomNameManager._singleton_initialized = True

    nm = SimpleNamespace(handler=_MockHandler(), sync_and_correct_notice_if_dialog_open=lambda: {'success': True})
    NoticeManager._instance = nm
    NoticeManager._singleton_initialized = True

    res = auditor.audit_all_in_open_window()
    assert isinstance(res, dict)
    assert 'recommendation' in res
    assert 'room_type' in res
    assert 'room_name' in res
    assert 'notice' in res


def test_room_info_auditor_pending_retry_flag():
    RoomInfoWindowAuditor.reset_instance()
    auditor = RoomInfoWindowAuditor.initialize()
    auditor._handler = _MockHandler()

    auditor.pending_audit_retry = False
    assert auditor.pending_audit_retry is False

    auditor.pending_audit_retry = True
    assert auditor.pending_audit_retry is True
