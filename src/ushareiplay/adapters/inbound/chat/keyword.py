import shlex

from ushareiplay.adapters.inbound.chat.base_command import BaseCommand
from ushareiplay.modules.command.domain import (
    ConfigKeywordImmutable,
    KeywordAlreadyPublic,
    KeywordEmpty,
    KeywordNotPublic,
    KeywordNotFound,
    MissingGrantees,
    NoKeywordsAdded,
    NotKeywordOwner,
    UserNotOnline,
)


class KeywordCommand(BaseCommand):
    handler_attr = 'soul_handler'
    error_message = '处理失败'

    def __init__(self, controller):
        super().__init__(controller)
        self.keyword_use_cases = controller.keyword_use_cases

    async def do_process(self, message_info, parameters):
        """Process keyword command

        Args:
            message_info: MessageInfo object containing original message content
            parameters: List of parameters (may be pre-split, use original content for proper parsing)

        Note: Uses original message content to properly parse quoted strings
        """
        # Get original message content from message_info to properly parse quoted strings
        # The content format is: "keyword 1 7 \":play 唯一的你;给你点首歌\""
        original_content = message_info.content

        self.handler.logger.info(
            f"Keyword command received: original_content={original_content}, parameters={parameters}"
        )

        # Parse the full command using shlex to handle quoted strings properly
        # Extract command name and parameters
        try:
            # Split by space to get command and rest
            parts = original_content.split(None, 1)  # Split only on first space
            if len(parts) < 2:
                return {'error': '缺少参数'}

            # Parse parameters using shlex
            params = shlex.split(parts[1])
        except ValueError as e:
            self.handler.log_error(f"Error parsing parameters: {str(e)}")
            return {'error': '参数格式错误，带空格的参数请使用引号包裹'}

        if not params:
            return {'error': '缺少参数'}

        operation = params[0].lower()

        # 规范化操作：将单词子命令转换为数字
        operation_map = {
            # 删除操作
            'delete': '0', 'del': '0', 'remove': '0', 'rm': '0',
            # 添加操作
            'add': '1', 'create': '1', 'new': '1',
            # 修改公开性操作
            'update': '2', 'modify': '2', 'toggle': '2', 'publicity': '2', 'public': '2',
            # 立即执行操作
            'execute': '3', 'exec': '3', 'run': '3', 'trigger': '3',
            # 授权/取消授权
            'grant': '4', 'allow': '4', 'auth': '4',
            'revoke': '5', 'ungrant': '5', 'unauth': '5', 'deny': '5',
        }

        # 如果是单词，转换为数字
        if operation in operation_map:
            operation = operation_map[operation]

        if operation == '0':
            # 删除关键字
            if len(params) < 2:
                return {'error': '缺少关键字参数'}
            keyword = params[1]
            try:
                message = await self.keyword_use_cases.delete_keyword(
                    message_info.nickname, keyword
                )
            except KeywordNotFound:
                return {'error': f'关键字 "{keyword}" 不存在'}
            except ConfigKeywordImmutable:
                return {'error': '不能删除配置关键字'}
            except NotKeywordOwner:
                return {'error': '只能删除自己创建的关键字'}
            except Exception:
                self.handler.log_error("Error deleting keyword")
                return {'error': '删除关键字失败'}
            return {'message': message}

        elif operation == '1':
            # 添加关键字
            if len(params) < 3:
                return {'error': '缺少参数：关键字或命令'}
            keywords = params[1]
            command = params[2]
            is_public = True if len(params) < 4 else (params[3] == '1')
            mode = params[4].lower() if len(params) >= 5 else "sequence"

            try:
                message = await self.keyword_use_cases.add_keyword(
                    message_info.nickname, keywords, command, is_public, mode
                )
            except UserNotOnline:
                return {'error': '只有在线用户才能添加关键字'}
            except KeywordEmpty:
                return {'error': '关键字不能为空'}
            except NoKeywordsAdded:
                return {'error': '没有关键字被添加'}
            except Exception:
                self.handler.log_error("Error adding keyword")
                return {'error': '添加关键字失败'}
            return {'message': message}

        elif operation == '2':
            # 修改公开性
            if len(params) < 2:
                return {'error': '缺少关键字参数'}
            keyword = params[1]

            # 解析公开性参数
            if len(params) < 3:
                # 省略参数，切换状态
                is_public = None
            else:
                # 指定参数
                is_public = (params[2] == '1')

            try:
                message = await self.keyword_use_cases.update_keyword_publicity(
                    message_info.nickname, keyword, is_public
                )
            except KeywordNotFound:
                return {'error': f'关键字 "{keyword}" 不存在'}
            except ConfigKeywordImmutable:
                return {'error': '不能修改配置关键字'}
            except NotKeywordOwner:
                return {'error': '只能修改自己创建的关键字'}
            except Exception:
                self.handler.log_error("Error updating keyword publicity")
                return {'error': '更新关键字公开性失败'}
            return {'message': message}

        elif operation == '3':
            # 立即执行关键字
            if len(params) < 2:
                return {'error': '缺少关键字参数'}
            keyword = params[1]

            # 查找关键字
            keyword_record = await self.keyword_use_cases.find_keyword(
                keyword, message_info.nickname
            )

            if not keyword_record:
                return {'error': f'关键字 "{keyword}" 不存在或无权限执行'}

            # 立即执行关键字
            await self.keyword_use_cases.execute_keyword(
                keyword_record,
                message_info.nickname,
                sleep_exempt=message_info.sleep_exempt,
            )

            return {'message': f'已执行关键字 "{keyword}"'}

        elif operation == '4':
            # 授权执行（私有关键字白名单）
            if len(params) < 3:
                return {'error': '缺少参数：关键字或授权用户'}
            keyword = params[1]
            target_usernames = "|".join([p.strip() for p in params[2:] if p.strip()])
            try:
                message = await self.keyword_use_cases.grant_keyword_access(
                    message_info.nickname, keyword, target_usernames
                )
            except KeywordNotFound:
                return {'error': f'关键字 "{keyword}" 不存在'}
            except ConfigKeywordImmutable:
                return {'error': '不能修改配置关键字'}
            except KeywordAlreadyPublic:
                return {'error': '公开关键字无需授权'}
            except NotKeywordOwner:
                return {'error': '只能授权自己创建的关键字'}
            except MissingGrantees:
                return {'error': '缺少授权用户'}
            except Exception:
                self.handler.log_error("Error granting keyword access")
                return {'error': '授权失败'}
            return {'message': message}

        elif operation == '5':
            # 取消授权执行（私有关键字白名单）
            if len(params) < 3:
                return {'error': '缺少参数：关键字或取消授权用户'}
            keyword = params[1]
            target_usernames = "|".join([p.strip() for p in params[2:] if p.strip()])
            try:
                message = await self.keyword_use_cases.revoke_keyword_access(
                    message_info.nickname, keyword, target_usernames
                )
            except KeywordNotFound:
                return {'error': f'关键字 "{keyword}" 不存在'}
            except ConfigKeywordImmutable:
                return {'error': '不能修改配置关键字'}
            except KeywordNotPublic:
                return {'error': '公开关键字无需取消授权'}
            except NotKeywordOwner:
                return {'error': '只能取消授权自己创建的关键字'}
            except MissingGrantees:
                return {'error': '缺少取消授权用户'}
            except Exception:
                self.handler.log_error("Error revoking keyword access")
                return {'error': '取消授权失败'}
            return {'message': message}

        else:
            return {'error': f'未知操作: {operation}'}
