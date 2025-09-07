import traceback
from datetime import datetime

from ..core.base_command import BaseCommand
from ..managers.timer_manager import TimerManager


def create_command(controller):
    timer_command = TimerCommand(controller)
    controller.timer_command = timer_command
    return timer_command


command = None


class TimerCommand(BaseCommand):

    def __init__(self, controller):
        super().__init__(controller)

        self.handler = controller.soul_handler
        self.timer_manager = TimerManager.instance()
        
        # Timer manager will be started by app_controller

    async def process(self, message_info, parameters):
        """Process timer command"""
        try:
            if not parameters:
                return self._list_timers()
            
            command = parameters[0].lower()
            
            if command == 'add':
                return await self._add_timer(parameters[1:])
            elif command == 'remove' or command == 'del':
                return await self._remove_timer(parameters[1:])
            elif command == 'list':
                return self._list_timers()
            elif command == 'help':
                return self._show_help()
            elif command == 'reset':
                return await self._reset_timers()
            else:
                return {'error': f'未知命令: {command}。使用 "timer help" 查看帮助'}
                
        except Exception as e:
            self.handler.log_error(f"Error processing timer command: {str(e)}")
            return {'error': f'处理定时器命令失败: {str(e)}'}

    async def _add_timer(self, parameters):
        """Add a new timer
        Args:
            parameters: [timer_id, time, message, repeat?]
        Returns:
            dict: Result with success or error
        """
        if len(parameters) < 3:
            return {'error': '参数不足。格式: timer add <ID> <时间> <消息> [repeat]'}
        
        timer_id = parameters[0]
        target_time = parameters[1]
        message = ' '.join(parameters[2:])
        
        # Check if repeat is specified
        repeat = False
        if message.endswith(' repeat'):
            repeat = True
            message = message[:-7].strip()  # Remove ' repeat' from message
        
        # Validate timer_id
        timers = self.timer_manager.get_timers()
        if timer_id in timers:
            return {'error': f'定时器ID "{timer_id}" 已存在'}
        
        # 注意参数顺序：TimerManager.add_timer(timer_id, message, target_time, repeat)
        result = await self.timer_manager.add_timer(timer_id, message, target_time, repeat)
        
        if not result:
            return {'error': '添加定时器失败'}
        
        repeat_text = " (每日重复)" if repeat else ""
        # 从管理器获取刚添加的定时器详情
        timer_data = self.timer_manager.get_timer(timer_id)
        next_trigger_str = ''
        if timer_data and timer_data.get('next_trigger'):
            try:
                from datetime import datetime
                next_trigger_dt = datetime.fromisoformat(timer_data['next_trigger'])
                next_trigger_str = next_trigger_dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                next_trigger_str = timer_data.get('next_trigger', '')

        return {
            'timer': f'定时器已添加{repeat_text}:\n'
                    f'ID: {timer_id}\n'
                    f'时间: {target_time}\n'
                    f'下次触发: {next_trigger_str}\n'
                    f'消息: {message}'
        }

    async def _remove_timer(self, parameters):
        """Remove a timer
        Args:
            parameters: [timer_id]
        Returns:
            dict: Result with success or error
        """
        if len(parameters) < 1:
            return {'error': '请指定要删除的定时器ID'}
        
        timer_id = parameters[0]
        result = await self.timer_manager.remove_timer(timer_id)
        if not result:
            return {'error': f'删除定时器失败: {timer_id} 不存在'}
        return {'timer': f'定时器 {timer_id} 已删除'}

    def _list_timers(self):
        """List all timers
        Returns:
            dict: List of all timers
        """
        timers = self.timer_manager.get_timers()
        
        if not timers:
            return {'timer': '没有定时器'}
        
        timer_list = []
        for timer_id, timer_data in timers.items():
            if not timer_data.get('enabled', True):
                continue
                
            repeat_text = " (每日重复)" if timer_data.get('repeat', False) else ""
            next_trigger = timer_data.get('next_trigger', '')
            if next_trigger:
                try:
                    from datetime import datetime
                    next_trigger_dt = datetime.fromisoformat(next_trigger)
                    next_trigger_str = next_trigger_dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    next_trigger_str = next_trigger
            else:
                next_trigger_str = '未设置'
                
            timer_list.append(
                f"• {timer_id}: {timer_data.get('target_time', '')}{repeat_text}\n"
                f"  下次触发: {next_trigger_str}\n"
                f"  消息: {timer_data.get('message', '')}"
            )
        
        return {
            'timer': f'定时器列表 (共{len(timer_list)}个):\n' + '\n\n'.join(timer_list)
        }

    def _show_help(self):
        """Show help information
        Returns:
            dict: Help message
        """
        help_text = """定时器命令帮助:

• timer list - 列出所有定时器
• timer add <ID> <时间> <消息> [repeat] - 添加定时器
• timer remove <ID> - 删除定时器
• timer reset - 重置所有定时器（清除现有数据）
• timer help - 显示此帮助

时间格式: HH:MM 或 HH:MM:SS
示例:
  timer add morning 08:00 早上好！
  timer add reminder 14:30:00 下午茶时间 repeat
  timer remove morning
  timer reset"""
        
        return {'timer': help_text}

    async def _reset_timers(self):
        """Reset all timers
        Returns:
            dict: Result with success or error
        """
        # Clear all timers
        timers = self.timer_manager.get_timers()
        ok = True
        for timer_id in list(timers.keys()):
            ok = ok and await self.timer_manager.remove_timer(timer_id)
        return {'timer': '所有定时器已重置' if ok else '部分定时器重置失败'}

    def update(self):
        """Update method for background tasks"""
        # Timer manager runs in its own thread, no need for periodic updates here
        pass

    async def stop(self):
        """Stop timer manager when command is destroyed"""
        if hasattr(self, 'timer_manager'):
            await self.timer_manager.stop()
