"""
座位容器事件 - 监控可见座位的占位变化。

折叠视口下只暴露部分座位容器（通常是首排）；本事件把可见座位的占位掩码交给
SeatManager 的被动探测器，由其防抖后触发差量抽检，而不是在这里直接点击。

座位号的推导沿用座位面板的排布约定：第 d 个容器对应 2d+1（左）与 2d+2（右）。
折叠时容器可能不全，因此掩码只描述"看得见的那部分"——探测器会自己还原真相。

注意：本事件只做信号上报，始终返回 False，不参与页面事件的中断判定。
"""

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.seat_manager.desks import SIDES, seat_number_of
from ushareiplay.managers.seat_manager.roster import SEAT_NUMBERS

__elements__ = ["seat_desk"]
__multiple__ = True


class SeatDeskEvent(BaseEvent):
    """座位容器占位变化的事件处理器"""

    async def handle(self, key: str, element_wrapper):
        try:
            if not element_wrapper:
                return False
            containers = (
                element_wrapper
                if isinstance(element_wrapper, list)
                else [element_wrapper]
            )
            if not containers or not any(containers):
                return False
            watcher = _seat_roster_watcher(self.handler)
            if watcher is None:
                return False

            watcher.note_occupancy_mask(_occupancy_mask(self.handler, containers))
            return False

        except Exception as e:
            self.logger.error(f"Error processing seat desk event: {str(e)}")
            return False


def _occupancy_mask(handler, containers) -> tuple:
    """十二个席位的占位值，按容器顺序推导；看不见的席位记为 None。

    只描述当前视口中可见座位的真实状态（True/False），视口外未展示的席位记为 None，
    避免折叠时被误判为空位而触发误报或反复探测。
    """
    mask = [None] * len(SEAT_NUMBERS)
    selectors = {
        side: _selector(handler, f"{side}_state") for side in SIDES
    }

    for desk_index, container in enumerate(containers):
        if container is None:
            continue
        for side in SIDES:
            seat_number = seat_number_of(desk_index, side)
            if seat_number not in SEAT_NUMBERS:
                continue
            mask[seat_number - 1] = _has_child(container, selectors[side])
    return tuple(mask)


def _has_child(container, selector) -> bool:
    if not selector:
        return False
    try:
        if selector.startswith("//"):
            return container.find_child_element("." + selector) is not None
        return (
            container.find_child_element(f".//*[@resource-id='{selector}']") is not None
        )
    except Exception:
        # A container that cannot be inspected is treated as empty; the probe
        # re-reads the real state anyway.
        return False


def _selector(handler, key: str):
    elements = _elements(handler)
    value = elements.get(key)
    return value if isinstance(value, str) and value else None


def _elements(handler) -> dict:
    """元素表可能挂在 config 顶层，也可能挂在 soul 段下（与 EventManager 一致）。"""
    config = getattr(handler, "config", None)
    if isinstance(config, dict):
        if isinstance(config.get("elements"), dict):
            return config["elements"]
        soul = config.get("soul")
        if isinstance(soul, dict) and isinstance(soul.get("elements"), dict):
            return soul["elements"]

    controller = getattr(handler, "controller", None)
    root_config = getattr(controller, "config", None)
    if isinstance(root_config, dict):
        soul = root_config.get("soul")
        if isinstance(soul, dict) and isinstance(soul.get("elements"), dict):
            return soul["elements"]
    return {}


def _seat_roster_watcher(handler):
    try:
        from ushareiplay.managers.seat_manager import SeatManager

        return SeatManager.get_instance().get_watcher()
    except Exception as e:
        logger = getattr(handler, "logger", None)
        if logger is not None:
            logger.error(f"Error reaching the seat roster watcher: {str(e)}")
        return None
