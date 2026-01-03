"""
事件模块目录

每个事件是一个独立的 Python 文件，文件名为元素 key（支持逗号分隔多个 key）。
例如：
- message_list.py - 监控消息列表
- close_button,confirm.py - 多个元素共用同一个事件处理
- risk_elements.py - 使用 __elements__ 字段指定要监控的元素列表

事件类命名规则：
1. 首个 key 转 PascalCase + Event（如 message_list -> MessageListEvent）
2. 如果模块有 __event__ 属性，使用该值作为类名

元素注册规则：
1. 如果模块有 __elements__ 字段（列表），优先使用该字段注册元素
2. 否则从文件名解析（逗号分隔的多个 key）
3. 使用 __elements__ 可以让文件名更简洁，避免过长的文件名
"""

