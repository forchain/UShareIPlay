import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict

from ushareiplay.core.message_queue import MessageQueue
from ushareiplay.core.singleton import Singleton


class TimerManager(Singleton):
    """
    管理器 - 使用协程实现
    管理定时任务的执行和重复，数据持久化到数据库
    """

    def __init__(self):
        self._handler = None
        self._logger = None
        self._timers = {}
        self._running = False
        self._task = None
        self._initialized = False

    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ushareiplay.handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler

    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger

    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """启动异步循环"""
        if self._running:
            self.logger.warning("Timer manager is already running")
            return

        if not self._initialized:
            await self._load_timers()

            # 首次运行：DB 为空时从 timers.json 迁移
            if not self._timers:
                await self._migrate_from_json()

            self._initialized = True
            self.logger.info(f"Loaded {len(self._timers)} timers on startup")

        self._running = True
        self._task = asyncio.create_task(self._timer_loop())
        self.logger.info("Timer manager started")

    async def stop(self):
        """停止异步循环"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Timer manager stopped")

    async def reload(self) -> int:
        """从数据库重新加载所有定时器，覆盖内存缓存"""
        await self._load_timers()
        count = len(self._timers)
        self.logger.info(f"Reloaded {count} timers from database")
        return count

    async def _timer_loop(self):
        """异步主循环"""
        loop_count = 0

        while self._running:
            try:
                current_time = datetime.now()
                loop_count += 1

                if loop_count % 60 == 0:
                    enabled_timers = sum(1 for t in self._timers.values() if t.get('enabled', False))

                for timer_key, timer_data in list(self._timers.items()):
                    if not isinstance(timer_data, dict):
                        self.logger.error(
                            f"Invalid timer data format for {timer_key}: {type(timer_data)} - {timer_data}")
                        del self._timers[timer_key]
                        continue

                    if not timer_data.get('enabled', False):
                        continue

                    next_trigger_str = timer_data.get('next_trigger')
                    if not next_trigger_str:
                        continue

                    try:
                        next_trigger = datetime.fromisoformat(next_trigger_str)
                        if current_time >= next_trigger:
                            self.logger.info(f"Triggering timer {timer_key} at {current_time}")
                            await self._trigger_timer(timer_key, timer_data)
                    except ValueError as e:
                        self.logger.error(f"Invalid next_trigger format for timer {timer_key}: {e}")
                        continue

                await asyncio.sleep(1)

            except Exception as e:
                self.logger.error(f"Error in timer loop: {str(e)}")
                await asyncio.sleep(5)

    async def _trigger_timer(self, timer_key: str, timer_data: dict):
        """触发并添加消息到队列"""
        from ushareiplay.dal.timer_dao import TimerDAO

        try:
            message = timer_data['message']
            self.logger.info(f"Timer {timer_key} triggered: {message}")

            from ushareiplay.models.message_info import MessageInfo
            message_info = MessageInfo(
                content=message,
                nickname="Timer"
            )

            message_queue = MessageQueue.instance()
            await message_queue.put_message(message_info)
            self.logger.info(f"Timer message added to queue: {message}")

            if timer_data.get('repeat', False):
                next_trigger = datetime.fromisoformat(timer_data['next_trigger']) + timedelta(days=1)
                timer_data['next_trigger'] = next_trigger.isoformat()
                await TimerDAO.update_next_trigger(timer_key, next_trigger)
                self.logger.info(f"Timer {timer_key} scheduled for next day: {next_trigger}")
            else:
                timer_data['enabled'] = False
                await TimerDAO.update_enabled(timer_key, False)
                self.logger.info(f"Timer {timer_key} completed and disabled")

        except Exception as e:
            self.logger.error(f"Error triggering timer {timer_key}: {str(e)}")

    async def _sanitize_db(self):
        """ORM 加载前用原生 SQL 修正不合法的 next_trigger 值（如带时区后缀）"""
        from tortoise import connections
        try:
            conn = connections.get("default")
            # 去掉时区后缀（如 +00:00）并补齐单位数小时（如 1:00:00 → 01:00:00）
            rows = await conn.execute_query(
                "SELECT id, key, next_trigger FROM timer_events WHERE next_trigger IS NOT NULL"
            )
            for row in rows[1]:
                raw = row['next_trigger'] if isinstance(row, dict) else row[2]
                key = row['key'] if isinstance(row, dict) else row[1]
                row_id = row['id'] if isinstance(row, dict) else row[0]
                if not isinstance(raw, str):
                    continue
                fixed = raw
                # 去掉时区后缀
                if '+' in fixed.split(' ')[-1]:
                    fixed = fixed.rsplit('+', 1)[0]
                # 补齐 "2026-03-20 1:00:00" → "2026-03-20 01:00:00"
                parts = fixed.split(' ')
                if len(parts) == 2 and len(parts[1].split(':')[0]) == 1:
                    parts[1] = '0' + parts[1]
                    fixed = ' '.join(parts)
                if fixed != raw:
                    await conn.execute_query(
                        "UPDATE timer_events SET next_trigger = ? WHERE id = ?",
                        [fixed, row_id],
                    )
        except Exception as e:
            self.logger.error(f"Error sanitizing timer DB: {str(e)}")

    async def _load_timers(self):
        """从数据库加载所有定时器到内存缓存，跳过积压的已过期触发"""
        from ushareiplay.dal.timer_dao import TimerDAO

        await self._sanitize_db()

        try:
            timers = await TimerDAO.list_all()
        except Exception as e:
            self.logger.error(f"Error querying timers from database: {str(e)}")
            self._timers = {}
            return

        self._timers = {}
        for t in timers:
            try:
                nt = t.next_trigger
                if nt and nt.tzinfo is not None:
                    nt = nt.replace(tzinfo=None)
                # 启动时跳过积压：若 next_trigger 已过期则推算下一个未来触发时间
                if nt and nt <= datetime.now() and t.repeat and t.target_time:
                    try:
                        target_time_obj = datetime.strptime(t.target_time, '%H:%M').time()
                        nt = datetime.combine(datetime.now().date(), target_time_obj)
                        if nt <= datetime.now():
                            nt += timedelta(days=1)
                        await TimerDAO.update_next_trigger(t.key, nt)
                    except ValueError:
                        pass
                self._timers[t.key] = {
                    'id': t.id,
                    'key': t.key,
                    'message': t.message,
                    'target_time': t.target_time,
                    'repeat': t.repeat,
                    'enabled': t.enabled,
                    'next_trigger': nt.isoformat() if nt else '',
                }
            except Exception as e:
                self.logger.error(f"Error loading timer {t.key}: {str(e)}, skipping")
        self.logger.info(f"Loaded {len(self._timers)} timers from database")

    async def _migrate_from_json(self):
        """首次运行时从 timers.json 迁移数据到数据库"""
        from ushareiplay.dal.timer_dao import TimerDAO

        timers_file = Path(__file__).parent.parent.parent.parent / 'data' / 'timers.json'
        if not timers_file.exists():
            return

        try:
            with open(timers_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)

            count = 0
            for timer_key, timer_data in loaded.items():
                if not isinstance(timer_data, dict):
                    continue
                next_trigger = None
                nt_str = timer_data.get('next_trigger', '')
                if nt_str:
                    try:
                        next_trigger = datetime.fromisoformat(nt_str)
                    except ValueError:
                        pass

                _, created = await TimerDAO.get_or_create(
                    key=timer_key,
                    defaults=dict(
                        message=timer_data.get('message', ''),
                        target_time=timer_data.get('target_time', ''),
                        repeat=timer_data.get('repeat', False),
                        enabled=timer_data.get('enabled', True),
                        next_trigger=next_trigger,
                    ),
                )
                if created:
                    count += 1

            self.logger.info(f"Migrated {count} timers from timers.json to database")
            await self._load_timers()

        except Exception as e:
            self.logger.error(f"Error migrating timers from JSON: {str(e)}")

    def get_timers(self) -> Dict[str, dict]:
        """Get all timers"""
        return self._timers.copy()

    def get_timer(self, timer_key: str) -> dict:
        """Get specific timer"""
        return self._timers.get(timer_key, {})

    async def add_timer(self, timer_key: str, message: str, target_time: str, repeat: bool = False) -> bool:
        """Add a new timer"""
        from ushareiplay.dal.timer_dao import TimerDAO

        try:
            target_time_obj = datetime.strptime(target_time, '%H:%M').time()
            today = datetime.now().date()
            target_datetime = datetime.combine(today, target_time_obj)

            if target_datetime <= datetime.now():
                target_datetime += timedelta(days=1)

            await TimerDAO.create(
                key=timer_key,
                message=message,
                target_time=target_time,
                repeat=repeat,
                enabled=True,
                next_trigger=target_datetime,
            )

            self._timers[timer_key] = {
                'key': timer_key,
                'message': message,
                'target_time': target_time,
                'repeat': repeat,
                'enabled': True,
                'next_trigger': target_datetime.isoformat(),
            }

            self.logger.info(f"Added timer {timer_key}: {message} at {target_time}")
            return True

        except Exception as e:
            self.logger.error(f"Error adding timer {timer_key}: {str(e)}")
            return False

    async def remove_timer(self, timer_key: str) -> bool:
        """Remove a timer"""
        from ushareiplay.dal.timer_dao import TimerDAO

        try:
            deleted = await TimerDAO.delete_by_key(timer_key)
            if deleted:
                self._timers.pop(timer_key, None)
                self.logger.info(f"Removed timer {timer_key}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error removing timer {timer_key}: {str(e)}")
            return False

    async def enable_timer(self, timer_key: str) -> bool:
        """Enable a timer"""
        from ushareiplay.dal.timer_dao import TimerDAO

        try:
            updated = await TimerDAO.update_enabled(timer_key, True)
            if updated and timer_key in self._timers:
                self._timers[timer_key]['enabled'] = True
                self.logger.info(f"Enabled timer {timer_key}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error enabling timer {timer_key}: {str(e)}")
            return False

    async def disable_timer(self, timer_key: str) -> bool:
        """Disable a timer"""
        from ushareiplay.dal.timer_dao import TimerDAO

        try:
            updated = await TimerDAO.update_enabled(timer_key, False)
            if updated and timer_key in self._timers:
                self._timers[timer_key]['enabled'] = False
                self.logger.info(f"Disabled timer {timer_key}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error disabling timer {timer_key}: {str(e)}")
            return False
