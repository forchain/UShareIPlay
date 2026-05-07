import functools
import traceback
from selenium.common.exceptions import (
    InvalidSessionIdException,
    WebDriverException
)


def with_driver_recovery(func=None, *, retry: bool = True, op: str = "read"):
    """
    装饰器：统一处理driver失效异常
    
    使用方式：
        @with_driver_recovery
        def some_read_method(self):
            ...

        @with_driver_recovery(retry=False, op="write")
        def some_method(self):
            self.driver.do_something()
    
    功能：
        - 捕获 InvalidSessionIdException 和相关异常
        - 触发 controller.reinitialize_driver() 重建driver
        - 恢复成功后是否重试由策略控制：
          - 读操作（默认）：允许重试一次
          - 写操作（推荐）：默认不自动重试，避免重复副作用
    """

    def decorator(f):
        @functools.wraps(f)
        def wrapper(self, *args, **kwargs):
            try:
                return f(self, *args, **kwargs)
            except (InvalidSessionIdException, WebDriverException) as e:
                # 延迟导入避免循环依赖
                from ushareiplay.core.app_controller import AppController

                controller = AppController.instance()
                if not controller:
                    return None

                ok = False
                try:
                    ok = bool(controller.reinitialize_driver())
                except Exception:
                    ok = False

                try:
                    if ok and getattr(controller, "obs", None):
                        controller.obs.emit(
                            "recovery.reinitialized",
                            ctx={"method": f.__name__, "op": op, "retry": retry},
                        )
                except Exception:
                    pass

                if not ok:
                    try:
                        if getattr(controller, "obs", None):
                            controller.obs.emit(
                                "recovery.failed",
                                level="ERROR",
                                ctx={"method": f.__name__, "op": op, "error": str(e)},
                            )
                    except Exception:
                        pass
                    return None

                if not retry:
                    try:
                        if getattr(controller, "obs", None):
                            controller.obs.emit(
                                "recovery.no_retry",
                                ctx={"method": f.__name__, "op": op},
                            )
                    except Exception:
                        pass
                    return None

                try:
                    if getattr(controller, "obs", None):
                        controller.obs.emit(
                            "recovery.retry",
                            ctx={"method": f.__name__, "op": op},
                        )
                except Exception:
                    pass

                try:
                    return f(self, *args, **kwargs)
                except Exception:
                    try:
                        if getattr(controller, "obs", None):
                            controller.obs.emit(
                                "recovery.retry_failed",
                                level="ERROR",
                                ctx={"method": f.__name__, "op": op, "error": traceback.format_exc()},
                            )
                    except Exception:
                        pass
                    return None

        return wrapper

    if func is None:
        return decorator
    return decorator(func)
