import functools
import traceback
from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException
)


def with_driver_recovery(func):
    """
    装饰器：统一处理driver失效异常
    
    使用方式：
        @with_driver_recovery
        def some_method(self):
            self.driver.do_something()
    
    功能：
        - 捕获 InvalidSessionIdException 和相关异常
        - 触发 controller.reinitialize_driver() 重建driver
        - 不重试，直接返回错误信息
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (InvalidSessionIdException, WebDriverException) as e:
            error_msg = str(e)
            
            # 检查是否是session失效错误
            is_session_invalid = (
                isinstance(e, InvalidSessionIdException) or
                "session is either terminated" in error_msg or
                "InvalidSessionIdException" in error_msg
            )
            
            if is_session_invalid:
                # 获取logger（优先从self，否则从handler）
                logger = getattr(self, 'logger', None)
                if logger is None and hasattr(self, 'handler'):
                    logger = getattr(self.handler, 'logger', None)
                
                if logger:
                    logger.warning(f"{func.__name__} 检测到driver session失效")
                
                # 获取controller并触发重建
                controller = _get_controller(self)
                if controller:
                    success = controller.reinitialize_driver()
                    if logger:
                        if success:
                            logger.info(f"Driver重建成功，{func.__name__} 返回错误")
                        else:
                            logger.error(f"Driver重建失败，{func.__name__} 返回错误")
                
                # 不重试，直接返回错误
                return {
                    'error': 'Driver session失效已重建',
                    'method': func.__name__,
                    'original_error': error_msg
                }
            else:
                # 其他WebDriver异常，记录后重新抛出
                logger = getattr(self, 'logger', None)
                if logger:
                    logger.error(f"{func.__name__} WebDriver错误: {traceback.format_exc()}")
                raise
                
    return wrapper


def _get_controller(obj):
    """获取controller引用的辅助函数"""
    # 直接从对象获取
    if hasattr(obj, 'controller'):
        return obj.controller
    
    # 从handler获取
    if hasattr(obj, 'handler') and hasattr(obj.handler, 'controller'):
        return obj.handler.controller
    
    # 从music_handler获取
    if hasattr(obj, 'music_handler') and hasattr(obj.music_handler, 'controller'):
        return obj.music_handler.controller
    
    return None

