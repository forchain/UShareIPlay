"""定时器用例：持久化、时钟与消息出口都从构造函数注入。"""

import asyncio
import logging
import secrets
from dataclasses import replace
from datetime import datetime

from ushareiplay.modules.shared.ports import Clock
from ushareiplay.modules.timer.domain import (
    Timer,
    TimerError,
    TimerKeyConflict,
    advance_repeat,
    compute_next_trigger,
    next_daily_trigger,
)
from ushareiplay.modules.timer.ports import TimerMessageSink, TimerRepository


class TimerUseCases:
    """定时任务管理：创建、删除、加载与到点投递。"""

    def __init__(
        self,
        *,
        repository: TimerRepository,
        clock: Clock,
        sink: TimerMessageSink,
        logger: logging.Logger | None = None,
    ):
        self._repository = repository
        self._clock = clock
        self._sink = sink
        self._logger = logger or logging.getLogger("TimerManager")
        self._timers: dict[str, Timer] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._initialized = False
        self._paused = False

    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def status_line(self) -> str:
        """启停状态摘要，供 timer / info 命令共用"""
        total = len(self._timers)
        if not self._running:
            return f"定时器: 已停止，共 {total} 个"
        if self._paused:
            return f"定时器: 已暂停，共 {total} 个"
        return f"定时器: 运行中，共 {total} 个"

    def pause(self) -> None:
        """暂停定时器检查与触发"""
        self._paused = True
        self._logger.info("Timer manager paused")

    async def resume(self) -> None:
        """恢复定时器检查与触发，并跳过暂停期间积压的重复定时器"""
        self._paused = False
        await self._skip_expired_repeat_timers()
        self._logger.info("Timer manager resumed")

    async def start(self) -> None:
        """启动异步循环"""
        if self._running:
            self._logger.warning("Timer manager is already running")
            return

        if not self._initialized:
            await self._repository.prepare()
            await self._load_timers()
            self._initialized = True
            self._logger.info(f"Loaded {len(self._timers)} timers on startup")

        self._running = True
        self._task = asyncio.create_task(self._timer_loop())
        self._logger.info("Timer manager started")

    async def stop(self) -> None:
        """停止异步循环"""
        self._running = False
        self._paused = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._logger.info("Timer manager stopped")

    async def reload(self) -> int:
        """从持久化重新加载所有定时器，覆盖内存缓存"""
        await self._load_timers()
        count = len(self._timers)
        self._logger.info(f"Reloaded {count} timers from database")
        return count

    async def _timer_loop(self) -> None:
        """异步主循环"""
        loop_count = 0

        while self._running:
            try:
                if self._paused:
                    await self._clock.sleep(1)
                    continue

                current_time = self._clock.now()
                loop_count += 1

                if loop_count % 60 == 0:
                    enabled_timers = sum(1 for t in self._timers.values() if t.enabled)

                for timer_key, timer in list(self._timers.items()):
                    if not timer.enabled:
                        continue
                    if timer.next_trigger is None:
                        continue
                    if current_time >= timer.next_trigger:
                        self._logger.info(f"Triggering timer {timer_key} at {current_time}")
                        await self._trigger_timer(timer_key, timer)

                await self._clock.sleep(1)

            except Exception as e:
                self._logger.error(f"Error in timer loop: {str(e)}")
                await self._clock.sleep(5)

    async def _trigger_timer(self, timer_key: str, timer: Timer) -> None:
        """触发并把消息交给出站队列"""
        try:
            if self._paused:
                return

            self._logger.info(f"Timer {timer_key} triggered: {timer.message}")
            await self._sink.enqueue(timer.message, nickname="Timer", sleep_exempt=True)
            self._logger.info(f"Timer message added to queue: {timer.message}")

            if timer.repeat:
                next_trigger = advance_repeat(timer.next_trigger, self._clock.now())
                self._timers[timer_key] = replace(timer, next_trigger=next_trigger)
                await self._repository.update_next_trigger(timer_key, next_trigger)
                self._logger.info(f"Timer {timer_key} scheduled for next day: {next_trigger}")
            else:
                await self._repository.delete_by_key(timer_key)
                self._timers.pop(timer_key, None)
                self._logger.info(f"Timer {timer_key} completed and deleted")

        except Exception as e:
            self._logger.error(f"Error triggering timer {timer_key}: {str(e)}")

    async def _skip_expired_repeat_timers(self) -> None:
        """恢复时跳过暂停期间已过期的重复定时器，避免立即堆叠触发历史任务"""
        now = self._clock.now()
        for key, timer in list(self._timers.items()):
            if not timer.repeat or not timer.target_time or timer.next_trigger is None:
                continue
            if timer.next_trigger > now:
                continue
            try:
                new_nt = next_daily_trigger(timer.target_time, now)
            except ValueError:
                continue
            self._timers[key] = replace(timer, next_trigger=new_nt)
            try:
                await self._repository.update_next_trigger(key, new_nt)
            except Exception:
                pass
            self._logger.info(f"Timer {key} skipped backlog during pause, rescheduled to {new_nt}")

    async def _load_timers(self) -> None:
        """从持久化加载所有定时器到内存缓存，跳过积压的已过期触发"""
        try:
            timers = await self._repository.list_all()
        except Exception as e:
            self._logger.error(f"Error querying timers from database: {str(e)}")
            self._timers = {}
            return

        self._timers = {}
        now = self._clock.now()
        for timer in timers:
            try:
                next_trigger = timer.next_trigger
                if next_trigger and next_trigger.tzinfo is not None:
                    next_trigger = next_trigger.replace(tzinfo=None)
                # 启动时跳过积压：若 next_trigger 已过期则推算下一个未来触发时间
                if next_trigger and next_trigger <= now and timer.repeat and timer.target_time:
                    try:
                        next_trigger = next_daily_trigger(timer.target_time, now)
                        await self._repository.update_next_trigger(timer.key, next_trigger)
                    except (ValueError, TimerError):
                        pass
                self._timers[timer.key] = replace(timer, next_trigger=next_trigger)
            except Exception as e:
                self._logger.error(f"Error loading timer {timer.key}: {str(e)}, skipping")
        self._logger.info(f"Loaded {len(self._timers)} timers from database")

    def get_timers(self) -> dict[str, Timer]:
        """Get all timers"""
        return self._timers.copy()

    def get_timer(self, timer_key: str) -> Timer | None:
        """Get specific timer"""
        return self._timers.get(timer_key)

    def parse_target_time(self, target_time: str, repeat: bool = False) -> datetime:
        """Public parser/validator for timer time grammar."""
        return compute_next_trigger(target_time, repeat, self._clock.now())

    async def create_timer(
        self,
        *,
        message: str,
        target_time: str,
        repeat: bool = False,
        key: str | None = None,
    ) -> Timer:
        """Create a timer, allocating and retrying the key when none is supplied.

        Raises:
            InvalidTimerSpec: for invalid time grammar.
            TimerKeyConflict: for duplicate explicit key.
        """
        next_trigger = self.parse_target_time(target_time, repeat)
        target_time = (target_time or "").strip()

        if key is None:
            last_err: TimerError | None = None
            for _ in range(6):
                candidate = secrets.token_hex(4)
                if candidate in self._timers:
                    last_err = TimerKeyConflict(candidate)
                    continue
                try:
                    await self._repository.create(
                        key=candidate,
                        message=message,
                        target_time=target_time,
                        repeat=repeat,
                        enabled=True,
                        next_trigger=next_trigger,
                    )
                    key = candidate
                    break
                except TimerKeyConflict as e:
                    last_err = e
            if key is None:
                raise TimerError(
                    f'添加失败：生成ID冲突次数过多 ({last_err})' if last_err else '添加失败：生成ID冲突次数过多'
                )
        else:
            await self._repository.create(
                key=key,
                message=message,
                target_time=target_time,
                repeat=repeat,
                enabled=True,
                next_trigger=next_trigger,
            )

        timer = Timer(
            key=key,
            message=message,
            target_time=target_time,
            repeat=repeat,
            enabled=True,
            next_trigger=next_trigger,
        )
        self._timers[key] = timer
        self._logger.info(f"Added timer {key}: {message} at {target_time}")
        return timer

    async def fire_timer(self, timer_key: str) -> dict:
        """Manually fire a cached timer (used by tests and one-shot completion)."""
        timer = self._timers.get(timer_key)
        if timer is None:
            return {'error': f'Timer {timer_key} not found'}
        await self._trigger_timer(timer_key, timer)
        return {'fired': True}

    async def add_timer(self, timer_key: str, message: str, target_time: str, repeat: bool = False) -> bool:
        """Legacy low-level add; prefer create_timer."""
        await self.create_timer(key=timer_key, message=message, target_time=target_time, repeat=repeat)
        return True

    async def remove_timer(self, timer_key: str) -> bool:
        """Remove a timer"""
        try:
            deleted = await self._repository.delete_by_key(timer_key)
            if deleted:
                self._timers.pop(timer_key, None)
                self._logger.info(f"Removed timer {timer_key}")
                return True
            return False
        except Exception as e:
            self._logger.error(f"Error removing timer {timer_key}: {str(e)}")
            return False
