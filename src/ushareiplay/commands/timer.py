import re
import shlex

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.timer_manager import TimerManager


class TimerCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理命令失败: {error}'

    def __init__(self, controller):
        super().__init__(controller)
        self.timer_manager = TimerManager.instance()

    async def do_process(self, message_info, parameters):
        """Process timer command"""
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
        elif command == 'reload':
            return await self._reload_timers()
        elif command == 'start':
            return await self._start_timer_manager()
        elif command == 'stop':
            return await self._stop_timer_manager()
        else:
            return {'error': f'未知命令: {command}。使用 "timer help" 查看帮助'}

    @staticmethod
    def _strip_grouping_quotes(s: str) -> str:
        """去掉外层引号以及成对的分组引号片段。"""
        text = (s or "").strip()
        if not text:
            return text
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
            text = text[1:-1]
        text = re.sub(r'"([^"]*)"', r"\1", text)
        text = re.sub(r"'([^']*)'", r"\1", text)
        return text.strip()

    async def _add_timer(self, parameters):
        """Add a new timer
        Args:
            parameters: [timer_id, time, message, repeat?]
        Returns:
            dict: Result with success or error
        """
        if len(parameters) < 2:
            return {'error': '参数不足。格式: timer add <ID?> <时间> <消息> [repeat]'}

        if self.timer_manager.is_time_token(parameters[0]):
            timer_id = None
            target_time = parameters[0]
            message_parts = parameters[1:]
        else:
            if len(parameters) < 3:
                return {'error': '参数不足。格式: timer add <ID?> <时间> <消息> [repeat]'}
            timer_id = parameters[0]
            target_time = parameters[1]
            message_parts = parameters[2:]

        repeat = False
        if message_parts and str(message_parts[-1]).lower() == 'repeat':
            repeat = True
            message_parts = message_parts[:-1]

        message = self._strip_grouping_quotes(' '.join(message_parts))
        if not message:
            return {'error': '消息不能为空。格式: timer add <ID?> <时间> <消息> [repeat]'}

        try:
            timer_data = await self.timer_manager.create_timer(
                message=message,
                target_time=target_time,
                repeat=repeat,
                key=timer_id,
            )
        except ValueError as e:
            return {'error': str(e)}
        except Exception as e:
            return {'error': f'添加失败: {str(e)}'}

        repeat_text = " (每日重复)" if repeat else ""
        next_trigger_str = ''
        next_trigger = timer_data.get('next_trigger')
        if next_trigger:
            try:
                from datetime import datetime
                next_trigger_dt = datetime.fromisoformat(next_trigger)
                next_trigger_str = next_trigger_dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                next_trigger_str = str(next_trigger)

        return {
            'timer': f'已添加{repeat_text}:\n'
                    f'ID: {timer_data["key"]}\n'
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
            return {'error': '请指定要删除的ID'}

        timer_id = parameters[0]
        result = await self.timer_manager.remove_timer(timer_id)
        if not result:
            return {'error': f'删除失败: {timer_id} 不存在'}
        return {'timer': f' {timer_id} 已删除'}

    def _list_timers(self):
        """List all timers
        Returns:
            dict: List of all timers
        """
        timers = self.timer_manager.get_timers()

        if not timers:
            return {'timer': '没有'}

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
                except Exception:
                    next_trigger_str = next_trigger
            else:
                next_trigger_str = '未设置'

            timer_list.append(
                f"• {timer_id}: {timer_data.get('target_time', '')}{repeat_text}\n"
                f"  下次触发: {next_trigger_str}\n"
                f"  消息: {timer_data.get('message', '')}"
            )

        return {
            'timer': f'列表 (共{len(timer_list)}个):\n' + '\n\n'.join(timer_list)
        }

    def _show_help(self):
        """Show help information
        Returns:
            dict: Help message
        """
        help_text = """命令帮助:

• timer list - 列出所有
• timer add <ID?> <时间> <消息> [repeat] - 添加（ID可省略，系统自动生成）
• timer remove <ID> - 删除
• timer reload - 从数据库重新加载（直接改DB后使用）
• timer start - 启动功能
• timer stop - 停止功能
• timer reset - 重置所有（清除现有数据）
• timer help - 显示此帮助

时间格式: HH:MM 或 HH:MM:SS；若为纯数字 N，则表示延迟 N 秒执行
示例:
  timer add morning 08:00 早上好！
  timer add reminder 14:30:00 下午茶时间 repeat
  timer add 10 临时提醒
  timer remove morning
  timer start
  timer stop
  timer reset"""

        return {'timer': help_text}

    async def _reset_timers(self):
        """Reset all timers
        Returns:
            dict: Result with success or error
        """
        timers = self.timer_manager.get_timers()
        ok = True
        for timer_id in list(timers.keys()):
            ok = ok and await self.timer_manager.remove_timer(timer_id)
        return {'timer': '所有已重置' if ok else '部分重置失败'}

    async def _reload_timers(self):
        """Reload all timers from database
        Returns:
            dict: Result with count of loaded timers
        """
        count = await self.timer_manager.reload()
        return {'timer': f'已从数据库重新加载 {count} 个定时器'}

    async def _start_timer_manager(self):
        """Start timer manager
        Returns:
            dict: Result with success or error
        """
        if self.timer_manager.is_running():
            return {'timer': '功能已经在运行中'}

        await self.timer_manager.start()
        return {'timer': '功能已启动'}

    async def _stop_timer_manager(self):
        """Stop timer manager
        Returns:
            dict: Result with success or error
        """
        if not self.timer_manager.is_running():
            return {'timer': '功能已经停止'}

        await self.timer_manager.stop()
        return {'timer': '功能已停止'}

    def update(self):
        """Update method for background tasks"""
        pass

    async def stop(self):
        """Stop timer manager when command is destroyed"""
        if hasattr(self, 'timer_manager'):
            await self.timer_manager.stop()
