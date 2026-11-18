"""测试台：把旧单例名的房间档案 API 映射到注入式用例上。

生产代码已改成组合根构造并注入；大量既有行为测试仍按旧单例名驱动
（`initialize()` / `instance()` / `reset_instance()`）并直接给 handler。
这里保留这一层测试适配：handler 被翻译成用例需要的端口，断言一条不改。
"""

from ushareiplay.core.message_dispatch import MessageDispatch
from ushareiplay.core.singleton import Singleton
from ushareiplay.modules.room.ports import RoomProfileSurfacePort
from ushareiplay.modules.room.room_profile import RoomProfileManager as _RoomProfileManager
from ushareiplay.modules.shared.config import ConfigSectionView, ConfigView
from ushareiplay.modules.shared.ports import RoomMessenger


class _HandlerSurface(RoomProfileSurfacePort):
    """把测试 handler 的 element_finder / key_actions 接到房间档案端口上。"""

    def __init__(self, handler):
        self._handler = handler

    def switch_to_app(self) -> bool:
        return bool(self._handler.key_actions.switch_to_app())

    def read_room_title(self):
        handler = self._handler
        if handler is None or not hasattr(handler, "element_finder"):
            return None
        finder = handler.element_finder
        try:
            dialog_element = finder.wait_for_element('room_name_in_dialog', timeout=2)
            if dialog_element:
                text = finder.get_element_text(dialog_element)
                if isinstance(text, str) and text.strip():
                    return text.strip()
            room_title_element = finder.try_find_element('chat_room_title', log=False)
            if not room_title_element:
                return None
            text = finder.get_element_text(room_title_element)
            if isinstance(text, str) and text.strip():
                return text.strip()
            return None
        except Exception:
            return None

    def read_notice_text(self) -> str:
        handler = self._handler
        if handler is None or not hasattr(handler, "element_finder"):
            return ""
        finder = handler.element_finder
        element = finder.try_find_element('chat_room_notice', log=False)
        if element:
            text = (finder.get_element_text(element) or "").strip()
            if text and text != "编辑":
                return text
        return ""

    def read_row_text(self, key: str, *, wait: bool = False) -> str:
        handler = self._handler
        if handler is None or not hasattr(handler, "element_finder"):
            return ""
        finder = handler.element_finder
        try:
            if wait:
                element = finder.wait_for_element(key)
            else:
                element = finder.try_find_element(key, log=False)
            if not element:
                return ""
            return (finder.get_element_text(element) or "").strip()
        except Exception:
            return ""


class _DispatchMessenger(RoomMessenger):
    """旧测试靠 monkeypatch `MessageDispatch` 观察公屏播报，保持同一个出口。"""

    def __init__(self, handler):
        self._handler = handler

    def send_screen_message(self, message: str, silent: bool = False):
        if not MessageDispatch.is_initialized():
            return
        MessageDispatch.instance().bind_handler(self._handler).send_screen_message(message)


def _handler_config(handler):
    if handler is None:
        return ConfigSectionView('soul', {})
    config = handler.config if hasattr(handler, 'config') else None
    if isinstance(config, ConfigSectionView):
        return config
    if isinstance(config, ConfigView):
        section = config.maybe_section('soul')
        return section if section is not None else ConfigSectionView('soul', {})
    if isinstance(config, dict):
        return ConfigSectionView('soul', config)
    return ConfigSectionView('soul', {})


class RoomProfileManager(_RoomProfileManager, Singleton):
    """旧单例名 + 注入式用例：测试只换 import，行为断言不动。"""

    def __init__(
        self,
        handler=None,
        drawer_driver=None,
        settings_driver=None,
        room_state=None,
        *,
        surface=None,
        config=None,
        messenger=None,
        logger=None,
    ):
        super().__init__(
            handler=handler,
            drawer_driver=drawer_driver,
            settings_driver=settings_driver,
            room_state=room_state,
            surface=surface or _HandlerSurface(handler),
            config=config or _handler_config(handler),
            messenger=messenger or _DispatchMessenger(handler),
            logger=logger,
        )

    def adopt_handler(self, handler, drawer_driver=None, settings_driver=None):
        super().adopt_handler(
            handler,
            drawer_driver,
            settings_driver,
            surface=_HandlerSurface(handler),
            config=_handler_config(handler),
            messenger=_DispatchMessenger(handler),
        )
