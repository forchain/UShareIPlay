"""事件元素列表解析：配置优先，缺省回退模块默认列表。

判定规则（事件类与 EventManager 共用同一套，避免两处口径漂移）：
配置值只有在「非空列表且条目全部为字符串」时才算已声明；其余情况
（键缺省、null、空列表、类型错误、含非字符串条目）一律回退默认列表。

默认列表来自事件模块本身：模块的 `__elements__`，没有时按文件名派生
（逗号分隔的多个 key）。
"""

from typing import Iterable, List, Optional


def resolve_event_elements(
    config: Optional[dict],
    config_key: Optional[str],
    default_elements: Iterable[str],
) -> List[str]:
    """返回事件当前生效的元素 key 列表。

    Args:
        config: Soul 配置（handler.config，即 config.yaml 的 soul 段）
        config_key: 配置项名称；None 表示该事件不支持配置覆盖
        default_elements: 配置缺省时的回退列表

    Returns:
        元素 key 列表
    """
    if config_key and isinstance(config, dict):
        declared = config.get(config_key)
        if (
            isinstance(declared, list)
            and declared
            and all(isinstance(key, str) for key in declared)
        ):
            return list(declared)
    return list(default_elements)
