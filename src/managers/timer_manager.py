import asyncio
import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

from ..core.singleton import Singleton
from ..core.message_queue import MessageQueue


class TimerManager(Singleton):
    """
    定时器管理器 - 使用协程实现
    管理定时任务的执行和重复
    """
    
    def __init__(self):
        # 延迟初始化 handler，避免循环依赖
        self._handler = None
        self._logger = None
        self._timers = {}
        self._timers_file = Path(__file__).parent.parent.parent / 'data' / 'timers.json'
        self._running = False
        self._task = None
        self._initialized = False
    
    @property
    def handler(self):
        """延迟获取 SoulHandler 实例"""
        if self._handler is None:
            from ..handlers.soul_handler import SoulHandler
            self._handler = SoulHandler.instance()
        return self._handler
    
    @property
    def logger(self):
        """延迟获取 logger 实例"""
        if self._logger is None:
            self._logger = self.handler.logger
        return self._logger
    
    async def start(self):
        """启动异步定时器循环"""
        if self._running:
            self.logger.warning("Timer manager is already running")
            return
        
        # 确保在启动前加载现有定时器
        if not self._initialized:
            await self._load_timers()
            
            # 处理命令管理器设置的初始定时器
            if hasattr(self, '_initial_timers') and self._initial_timers:
                force_update = getattr(self, '_force_update', False)
                await self.load_initial_timers(self._initial_timers, force_update)
                # 清理临时属性
                delattr(self, '_initial_timers')
                if hasattr(self, '_force_update'):
                    delattr(self, '_force_update')
            
            self._initialized = True
            self.logger.info(f"Loaded {len(self._timers)} timers on startup")
        
        self._running = True
        self._task = asyncio.create_task(self._timer_loop())
        self.logger.info("Timer manager started")
    
    async def stop(self):
        """停止异步定时器循环"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Timer manager stopped")
    
    async def _timer_loop(self):
        """异步定时器主循环"""
        # self.logger.info(f"Timer loop started with {len(self._timers)} timers")
        loop_count = 0
        
        while self._running:
            try:
                current_time = datetime.now()
                loop_count += 1
                
                # 每60次循环（约1分钟）记录一次状态
                if loop_count % 60 == 0:
                    enabled_timers = sum(1 for t in self._timers.values() if t.get('enabled', False))
                    # self.logger.debug(f"Timer loop running: {enabled_timers}/{len(self._timers)} timers enabled")
                
                # Check each timer
                for timer_id, timer_data in list(self._timers.items()):
                    # Validate timer data format
                    if not isinstance(timer_data, dict):
                        self.logger.error(f"Invalid timer data format for {timer_id}: {type(timer_data)} - {timer_data}")
                        # Remove invalid timer data
                        del self._timers[timer_id]
                        continue
                    
                    if not timer_data.get('enabled', False):
                        continue
                    
                    # Check if it's time to trigger
                    next_trigger_str = timer_data.get('next_trigger')
                    if not next_trigger_str:
                        continue
                    
                    try:
                        next_trigger = datetime.fromisoformat(next_trigger_str)
                        if current_time >= next_trigger:
                            self.logger.info(f"Triggering timer {timer_id} at {current_time}")
                            await self._trigger_timer(timer_id, timer_data)
                    except ValueError as e:
                        self.logger.error(f"Invalid next_trigger format for timer {timer_id}: {e}")
                        continue
                
                # Sleep for 1 second before next check
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error in timer loop: {str(e)}")
                await asyncio.sleep(5)  # Wait longer on error
    
    async def _trigger_timer(self, timer_id: str, timer_data: dict):
        """触发定时器并添加消息到队列"""
        try:
            message = timer_data['message']
            self.logger.info(f"Timer {timer_id} triggered: {message}")
            
            # Create MessageInfo for queue
            from ..models.message_info import MessageInfo
            message_info = MessageInfo(
                content=message,
                nickname="Timer",
                avatar_element=None,
                relation_tag=True  # Timer messages are always authorized
            )
            
            # Add message to queue
            message_queue = MessageQueue.instance()
            await message_queue.put_message(message_info)
            self.logger.info(f"Timer message added to queue: {message}")
            
            # Update next trigger time
            if timer_data.get('repeat', False):
                # Daily repeat - only update next_trigger, keep target_time unchanged
                next_trigger = datetime.fromisoformat(timer_data['next_trigger']) + timedelta(days=1)
                timer_data['next_trigger'] = next_trigger.isoformat()
                self.logger.info(f"Updating timer {timer_id}: keeping target_time={timer_data.get('target_time')}, new next_trigger={next_trigger}")
                await self._save_timers()
                self.logger.info(f"Timer {timer_id} scheduled for next day: {next_trigger}")
            else:
                # One-time timer, disable it
                timer_data['enabled'] = False
                await self._save_timers()
                self.logger.info(f"Timer {timer_id} completed and disabled")
                
        except Exception as e:
            self.logger.error(f"Error triggering timer {timer_id}: {str(e)}")
    
    async def load_initial_timers(self, initial_timers: List[dict], force_update: bool = False):
        """Load initial timers from configuration"""
        try:
            # Load existing timers if file exists
            if self._timers_file.exists() and not force_update:
                await self._load_timers()
                self.logger.info(f"Loaded {len(self._timers)} existing timers")
            
            # Add initial timers
            for timer_config in initial_timers:
                timer_id = timer_config.get('id')
                if not timer_id:
                    self.logger.warning("Timer missing ID, skipping")
                    continue
                
                if timer_id in self._timers and not force_update:
                    self.logger.info(f"Timer {timer_id} already exists, skipping")
                    continue
                
                # Create timer data
                timer_data = {
                    'id': timer_id,
                    'message': timer_config.get('message', ''),
                    'target_time': timer_config.get('target_time', ''),
                    'repeat': timer_config.get('repeat', False),
                    'enabled': timer_config.get('enabled', True),
                    'next_trigger': timer_config.get('next_trigger', '')
                }
                
                # Calculate next trigger time if not set
                if not timer_data['next_trigger'] and timer_data['target_time']:
                    try:
                        target_time = datetime.strptime(timer_data['target_time'], '%H:%M').time()
                        today = datetime.now().date()
                        target_datetime = datetime.combine(today, target_time)
                        
                        # If time has passed today, schedule for tomorrow
                        if target_datetime <= datetime.now():
                            target_datetime += timedelta(days=1)
                        
                        timer_data['next_trigger'] = target_datetime.isoformat()
                    except ValueError as e:
                        self.logger.error(f"Invalid target_time format for timer {timer_id}: {e}")
                        continue
                
                self._timers[timer_id] = timer_data
                self.logger.info(f"Added timer {timer_id}: {timer_data['message']} at {timer_data['target_time']}")
            
            # Save timers
            await self._save_timers()
            self.logger.info(f"Loaded {len(self._timers)} timers total")
            
        except Exception as e:
            self.logger.error(f"Error loading initial timers: {str(e)}")
    
    async def _load_timers(self):
        """Load timers from file"""
        try:
            if self._timers_file.exists():
                with open(self._timers_file, 'r', encoding='utf-8') as f:
                    loaded_timers = json.load(f)
                
                # Validate and clean timer data
                self._timers = {}
                for timer_id, timer_data in loaded_timers.items():
                    if isinstance(timer_data, dict):
                        self._timers[timer_id] = timer_data
                    else:
                        self.logger.warning(f"Skipping invalid timer data for {timer_id}: {type(timer_data)} - {timer_data}")
                
                self.logger.info(f"Loaded {len(self._timers)} valid timers from file")
        except Exception as e:
            self.logger.error(f"Error loading timers: {str(e)}")
            self._timers = {}
    
    async def _save_timers(self):
        """Save timers to file"""
        try:
            # Ensure directory exists
            self._timers_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self._timers_file, 'w', encoding='utf-8') as f:
                json.dump(self._timers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving timers: {str(e)}")
    
    def get_timers(self) -> Dict[str, dict]:
        """Get all timers"""
        return self._timers.copy()
    
    def get_timer(self, timer_id: str) -> dict:
        """Get specific timer"""
        return self._timers.get(timer_id, {})
    
    async def add_timer(self, timer_id: str, message: str, target_time: str, repeat: bool = False) -> bool:
        """Add a new timer"""
        try:
            # Calculate next trigger time
            target_time_obj = datetime.strptime(target_time, '%H:%M').time()
            today = datetime.now().date()
            target_datetime = datetime.combine(today, target_time_obj)
            
            # If time has passed today, schedule for tomorrow
            if target_datetime <= datetime.now():
                target_datetime += timedelta(days=1)
            
            timer_data = {
                'id': timer_id,
                'message': message,
                'target_time': target_time,
                'repeat': repeat,
                'enabled': True,
                'next_trigger': target_datetime.isoformat()
            }
            
            self._timers[timer_id] = timer_data
            await self._save_timers()
            self.logger.info(f"Added timer {timer_id}: {message} at {target_time}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error adding timer {timer_id}: {str(e)}")
            return False
    
    async def remove_timer(self, timer_id: str) -> bool:
        """Remove a timer"""
        try:
            if timer_id in self._timers:
                del self._timers[timer_id]
                await self._save_timers()
                self.logger.info(f"Removed timer {timer_id}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error removing timer {timer_id}: {str(e)}")
            return False
    
    async def enable_timer(self, timer_id: str) -> bool:
        """Enable a timer"""
        try:
            if timer_id in self._timers:
                self._timers[timer_id]['enabled'] = True
                await self._save_timers()
                self.logger.info(f"Enabled timer {timer_id}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error enabling timer {timer_id}: {str(e)}")
            return False
    
    async def disable_timer(self, timer_id: str) -> bool:
        """Disable a timer"""
        try:
            if timer_id in self._timers:
                self._timers[timer_id]['enabled'] = False
                await self._save_timers()
                self.logger.info(f"Disabled timer {timer_id}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error disabling timer {timer_id}: {str(e)}")
            return False
