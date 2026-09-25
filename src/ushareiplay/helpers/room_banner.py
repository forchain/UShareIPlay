"""房间横幅文案（标题/话题）的清洗规则。

Soul 的房间名与话题都是单行短文本，聊天里传进来的内容可能带竖线、括号等
装饰或说明，需要先截到第一个装饰符之前再限长。房间名与话题原先各写了一份
完全相同的切分链（只有长度上限不同），规则因此有两处需要同步修改。
"""

#: 房间标题的展示长度上限
TITLE_MAX_LENGTH = 12
#: 房间话题的展示长度上限
TOPIC_MAX_LENGTH = 15

# 截断点：半角/全角竖线、CJK 竖笔，以及半角/全角左括号
_SEPARATORS = ('|', '｜', '丨', '(', '（')


def clean_banner_text(text: str, max_length: int) -> str:
    """把标题/话题文本截到第一个装饰符之前，去空白并限长。

    逐个分隔符依次截断（每个都在前一步的结果上继续切），与原先两份内联实现
    的切分顺序一致。

    >>> clean_banner_text('夜曲｜周杰伦', TITLE_MAX_LENGTH)
    '夜曲'
    >>> clean_banner_text('  晚安 | 早点睡  ', TOPIC_MAX_LENGTH)
    '晚安'
    """
    cleaned = text or ""
    for separator in _SEPARATORS:
        cleaned = cleaned.split(separator)[0]
    return cleaned.strip()[:max_length]
