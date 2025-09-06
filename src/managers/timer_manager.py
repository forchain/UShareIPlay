import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import os

from ..core.singleton import Singleton

class TimerManager(Singleton):
    def __init__(self):
        # Get SoulHandler singleton instance
        from ..handlers.soul_handler import SoulHandler
        self.handler = SoulHandler.instance()
        self.logger = self.handler.logger
        self.timers: Dict[str, dict] = {}
        self.timer_thread = None
        self.running = False
        self.timer_file = "data/timers.json"
        
        # Load timers from file
        self._load_timers()
        
    def _load_timers(self):
        """Load timers from JSON file"""
        try:
            if os.path.exists(self.timer_file):
                with open(self.timer_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.timers = data.get('timers', {})
                    self.logger.info(f"Loaded {len(self.timers)} timers from file")
            else:
                self.logger.info("No timer file found, starting with empty timers")
        except Exception as e:
            self.logger.error(f"Error loading timers: {str(e)}")
            self.timers = {}
    
    def _save_timers(self):
        """Save timers to JSON file"""
        try:
            os.makedirs(os.path.dirname(self.timer_file), exist_ok=True)
            data = {
                'timers': self.timers,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.timer_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved {len(self.timers)} timers to file")
        except Exception as e:
            self.logger.error(f"Error saving timers: {str(e)}")
    
    def add_timer(self, timer_id: str, target_time: str, message: str, repeat: bool = False) -> dict:
        """Add a new timer
        Args:
            timer_id: Unique identifier for the timer
            target_time: Target time in format "HH:MM" or "HH:MM:SS"
            message: Message to send when timer triggers
            repeat: Whether to repeat daily
        Returns:
            dict: Result with success or error
        """
        try:
            # Parse target time
            time_parts = target_time.split(':')
            if len(time_parts) < 2:
                return {'error': '时间格式错误，请使用 HH:MM 或 HH:MM:SS 格式'}
            
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            second = int(time_parts[2]) if len(time_parts) > 2 else 0
            
            if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                return {'error': '时间值超出范围，小时(0-23)，分钟(0-59)，秒(0-59)'}
            
            # Calculate next trigger time
            now = datetime.now()
            target_datetime = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            
            # If target time has passed today, set for tomorrow
            if target_datetime <= now:
                target_datetime += timedelta(days=1)
            
            timer_data = {
                'id': timer_id,
                'target_time': target_time,  # Keep original time string
                'message': message,
                'repeat': repeat,
                'next_trigger': target_datetime.isoformat(),
                'created_at': now.isoformat(),
                'enabled': True
            }
            
            self.logger.info(f"Creating timer {timer_id}: original_time={target_time}, calculated_datetime={target_datetime}")
            
            self.timers[timer_id] = timer_data
            
            # Debug: Log the data before and after saving
            self.logger.info(f"Before save - timer_data: {timer_data}")
            self._save_timers()
            self.logger.info(f"After save - self.timers[{timer_id}]: {self.timers[timer_id]}")
            
            self.logger.info(f"Added timer {timer_id}: {target_time} - {message}")
            return {
                'success': True,
                'timer_id': timer_id,
                'target_time': target_time,
                'next_trigger': target_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'message': message
            }
            
        except ValueError as e:
            return {'error': f'时间格式错误: {str(e)}'}
        except Exception as e:
            self.logger.error(f"Error adding timer: {str(e)}")
            return {'error': f'添加定时器失败: {str(e)}'}
    
    def remove_timer(self, timer_id: str) -> dict:
        """Remove a timer
        Args:
            timer_id: Timer ID to remove
        Returns:
            dict: Result with success or error
        """
        if timer_id not in self.timers:
            return {'error': f'定时器 {timer_id} 不存在'}
        
        timer_data = self.timers.pop(timer_id)
        self._save_timers()
        
        self.logger.info(f"Removed timer {timer_id}")
        return {
            'success': True,
            'timer_id': timer_id,
            'message': f'定时器 {timer_id} 已删除'
        }
    
    def list_timers(self) -> dict:
        """List all timers
        Returns:
            dict: List of all timers
        """
        if not self.timers:
            return {'timers': [], 'message': '没有定时器'}
        
        timer_list = []
        for timer_id, timer_data in self.timers.items():
            if timer_data.get('enabled', True):
                next_trigger = datetime.fromisoformat(timer_data['next_trigger'])
                timer_list.append({
                    'id': timer_id,
                    'target_time': timer_data['target_time'],
                    'message': timer_data['message'],
                    'repeat': timer_data.get('repeat', False),
                    'next_trigger': next_trigger.strftime('%Y-%m-%d %H:%M:%S'),
                    'created_at': timer_data.get('created_at', '')
                })
        
        return {
            'timers': timer_list,
            'count': len(timer_list)
        }
    
    def start(self):
        """Start the timer monitoring thread"""
        if self.running:
            return
        
        self.running = True
        self.timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self.timer_thread.start()
        self.logger.info("Timer manager started")
    
    def stop(self):
        """Stop the timer monitoring thread"""
        self.running = False
        if self.timer_thread:
            self.timer_thread.join(timeout=1)
        self.logger.info("Timer manager stopped")
    
    def _timer_loop(self):
        """Main timer monitoring loop"""
        while self.running:
            try:
                now = datetime.now()
                triggered_timers = []
                
                for timer_id, timer_data in self.timers.items():
                    if not timer_data.get('enabled', True):
                        continue
                    
                    next_trigger = datetime.fromisoformat(timer_data['next_trigger'])
                    
                    if now >= next_trigger:
                        triggered_timers.append((timer_id, timer_data))
                
                # Process triggered timers
                for timer_id, timer_data in triggered_timers:
                    self._trigger_timer(timer_id, timer_data)
                
                # Sleep for 1 second before next check
                time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error in timer loop: {str(e)}")
                time.sleep(5)  # Wait longer on error
    
    def _trigger_timer(self, timer_id: str, timer_data: dict):
        """Trigger a timer and send message"""
        try:
            message = timer_data['message']
            self.logger.info(f"Timer {timer_id} triggered: {message}")
            
            # Send message through handler
            if hasattr(self.handler, 'send_message'):
                self.handler.send_message(message)
            else:
                self.logger.warning("Handler does not support send_message")
            
            # Update next trigger time
            if timer_data.get('repeat', False):
                # Daily repeat - only update next_trigger, keep target_time unchanged
                next_trigger = datetime.fromisoformat(timer_data['next_trigger']) + timedelta(days=1)
                timer_data['next_trigger'] = next_trigger.isoformat()
                # Ensure target_time remains the original time string
                # (this should not be necessary, but adding as safeguard)
                self.logger.info(f"Updating timer {timer_id}: keeping target_time={timer_data.get('target_time')}, new next_trigger={next_trigger}")
                self._save_timers()
                self.logger.info(f"Timer {timer_id} scheduled for next day: {next_trigger}")
            else:
                # One-time timer, disable it
                timer_data['enabled'] = False
                self._save_timers()
                self.logger.info(f"Timer {timer_id} completed and disabled")
                
        except Exception as e:
            self.logger.error(f"Error triggering timer {timer_id}: {str(e)}")
    
    def load_initial_timers(self, initial_timers: List[dict], force_update: bool = False):
        """Load initial timers from configuration
        Args:
            initial_timers: List of timer configurations
            force_update: If True, update existing timers with config values
        """
        for timer_config in initial_timers:
            timer_id = timer_config.get('id')
            target_time = timer_config.get('time')
            message = timer_config.get('message')
            repeat = timer_config.get('repeat', False)
            
            self.logger.info(f"Loading initial timer: id={timer_id}, time={target_time}, message={message}")
            
            if timer_id and target_time and message:
                # Check if timer already exists
                if timer_id in self.timers:
                    if force_update:
                        # Update existing timer with config values
                        self.logger.info(f"Updating existing timer {timer_id} with config values")
                        result = self.add_timer(timer_id, target_time, message, repeat)
                        if 'error' in result:
                            self.logger.error(f"Failed to update initial timer {timer_id}: {result['error']}")
                        else:
                            self.logger.info(f"Updated initial timer {timer_id}")
                    else:
                        self.logger.info(f"Timer {timer_id} already exists, skipping (use force_update=True to override)")
                else:
                    # Add new timer
                    result = self.add_timer(timer_id, target_time, message, repeat)
                    if 'error' in result:
                        self.logger.error(f"Failed to load initial timer {timer_id}: {result['error']}")
                    else:
                        self.logger.info(f"Loaded initial timer {timer_id}")
            else:
                self.logger.warning(f"Invalid initial timer config: {timer_config}")

    def reset_timers(self):
        """Reset all timers (clear existing data and reload from config)"""
        try:
            # Clear existing timers
            self.timers.clear()
            self.logger.info("Cleared all existing timers")
            
            # Remove timer file
            if os.path.exists(self.timer_file):
                os.remove(self.timer_file)
                self.logger.info(f"Removed timer file: {self.timer_file}")
            
            return {'success': True, 'message': 'All timers reset successfully'}
        except Exception as e:
            self.logger.error(f"Error resetting timers: {str(e)}")
            return {'error': f'Failed to reset timers: {str(e)}'}
