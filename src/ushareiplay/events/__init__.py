"""
事件模块目录

每个事件是一个独立的 Python 文件，文件名为元素 key（支持逗号分隔多个 key）。
例如：
- close_button,confirm.py - 多个元素共用同一个事件处理
- risk_elements.py - 使用 __elements__ 字段指定要监控的元素列表

事件类命名规则：
1. 首个 key 转 PascalCase + Event（如 message_content -> MessageContentEvent）
2. 如果模块有 __event__ 属性，使用该值作为类名

元素注册规则：
1. 如果模块有 __elements__ 字段（列表），优先使用该字段注册元素
2. 否则从文件名解析（逗号分隔的多个 key）
3. 使用 __elements__ 可以让文件名更简洁，避免过长的文件名

多元素处理规则：
1. 如果模块有 __multiple__ 字段（布尔值），默认为 False
2. 如果 __multiple__ = True，则返回所有匹配的元素（列表），事件处理函数会被调用多次（每个元素一次）
3. 如果 __multiple__ = False，则只返回第一个匹配的元素（默认行为）
"""

