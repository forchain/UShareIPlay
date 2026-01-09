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
            # 延迟导入避免循环依赖
            from ..core.app_controller import AppController
            # 获取controller并触发重建
            if controller := AppController.instance():
                if controller.reinitialize_driver():
                    print(f"Driver重建成功，{func.__name__} ")
                    return func(self, *args, **kwargs)

            print(f"Driver重建失败，{func.__name__}, error:{e}")
            return None

    return wrapper
