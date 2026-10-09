"""
专注人数与麦位事件 - 监控 tvStudyRoomDesc（配置 key: focus_count）及可见 seat_desk 变化。

1. 专注人数变化或被动麦位变动时，维护 12 麦位 3 排视觉快照并输出至日志。
2. 当且仅当某位用户的麦位发生变更（上座、下座、换座）时，精准检索并入队该用户配置的 :focus add 联动命令。
3. 当专注人数与可视在座人数背离时，主动展开面板全量重扫并立即收起恢复现场。
"""

from typing import Optional

from ushareiplay.core.base_event import BaseEvent
from ushareiplay.managers.seat_manager.seat_observation import (
    SeatObservationManager,
    parse_focus_count_text,
)
from ushareiplay.state.room_state import RoomState

# 顺序即 EventManager 的同轮分发顺序（见 _process_events_once）：必须先被动观测
# 本页可见麦位，再判人数背离。反过来的话每一次可视上座都会拿旧快照去比，被误判
# 成背离而白展开一次面板。
__elements__ = ["seat_desk", "focus_count"]
__multiple__ = True


class FocusCountEvent(BaseEvent):
    """专注人数与麦位事件处理器"""

    previous_focus_count: Optional[int] = None

    def __init__(self, handler, runtime=None):
        super().__init__(handler, runtime)
        self.observation = SeatObservationManager.instance().bind_handler(handler)

    async def handle(self, key: str, element_wrapper):
        """
        处理 focus_count（专注人数）或 seat_desk（可见麦位）事件。

        Returns:
            False：不中断同轮其它事件处理。
        """
        try:
            if key == "focus_count":
                wrapper = element_wrapper[0] if isinstance(element_wrapper, list) else element_wrapper
                if not wrapper:
                    return False
                current_text = getattr(wrapper, "text", "") or ""

                current_focus_count = parse_focus_count_text(current_text)
                if current_focus_count is None:
                    return False

                before = self.previous_focus_count
                self.previous_focus_count = current_focus_count
                # 「人数没变」只该跳过背离判断，不能跳过缓存写入：RoomState.clear()
                # 之后 previous 仍是有值的旧数字，于是每次都早退、缓存永远是空的，
                # 日志就一直打「专注人数: 未知」（真机 10-10 01:49:30~01:50:32：
                # 连扫 4~5 遍、零次座位更新，每行都写着未知）。
                RoomState.instance().focus_count = current_focus_count

                if before == current_focus_count:
                    return False

                # 检查是否发生人数与在座人数背离，触发主动展开探测
                await self.observation.on_focus_count(before, current_focus_count)

            elif key == "seat_desk":
                desks = element_wrapper if isinstance(element_wrapper, list) else [element_wrapper]
                if not desks:
                    return False

                # 被动观测可视麦位。
                # 分发顺序把 seat_desk 排在 focus_count 前面，所以首轮 previous 必然是
                # None，这次观测会带着「未知」去对账 —— 而人数正是判断扫得对不对的
                # 唯一硬依据。缓存空时补读一次界面，**读到了就立刻写回缓存**：
                # 冷读只在进房/clear() 之后发生一次，不会变成每轮轮询都打 driver 的
                # 无行为监控（AGENTS.md 日志铁律）。读不到就保持 None，不猜。
                current_focus_count = self.previous_focus_count
                if current_focus_count is None:
                    current_focus_count = self.observation.read_focus_count_from_ui()
                    if current_focus_count is not None:
                        self.previous_focus_count = current_focus_count
                        RoomState.instance().focus_count = current_focus_count

                await self.observation.observe_visible_desks(
                    desks, current_focus_count=current_focus_count
                )

            return False

        except Exception as e:
            self.logger.error(f"Error processing focus count / seat event: {str(e)}")
            return False

