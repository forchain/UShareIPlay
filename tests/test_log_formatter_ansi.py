"""消息体自带 ANSI 转义码时，两种 sink 必须各自正确。

座次表给在座麦位上的色是写在消息体里的（整行着色做不到逐格子着色），而同一份
logger 同时挂文件 handler（use_colors=False）和控制台 handler（use_colors=True）：
文件里留下转义码，tail / grep 就全是乱码。
"""

import logging

from ushareiplay.core.log_formatter import ColoredFormatter, strip_ansi

COLORED_TABLE = (
    "第三排: \033[1;32m[9号: Outlier]\033[0m \033[90m[10号: 空闲]\033[0m\n"
    "  \033[1;36m[11号: Joyer]\033[0m"
)
PLAIN_TABLE = "第三排: [9号: Outlier] [10号: 空闲]\n  [11号: Joyer]"


def _record(message, level=logging.INFO):
    return logging.LogRecord("t", level, __file__, 1, message, None, None)


def test_strip_ansi_removes_only_escape_codes():
    assert strip_ansi(COLORED_TABLE) == PLAIN_TABLE
    assert strip_ansi("没有转义码的一行") == "没有转义码的一行"


def test_file_formatter_strips_message_escape_codes():
    formatted = ColoredFormatter("%(message)s", use_colors=False).format(_record(COLORED_TABLE))
    assert formatted == PLAIN_TABLE
    assert "\033" not in formatted


def test_console_formatter_keeps_message_escape_codes():
    formatted = ColoredFormatter("%(message)s", use_colors=True).format(_record(COLORED_TABLE))
    assert formatted == COLORED_TABLE


def test_console_formatter_still_colorizes_whole_warning_line():
    formatted = ColoredFormatter("%(message)s", use_colors=True).format(
        _record("\033[1;36m在座\033[0m", level=logging.WARNING)
    )
    assert formatted.startswith(ColoredFormatter.COLORS["WARNING"])
    assert formatted.endswith(ColoredFormatter.COLORS["RESET"])


def test_real_file_handler_writes_plain_text(tmp_path):
    """端到端：真 FileHandler 落盘的内容必须是纯文本（多行消息也算）。"""
    log_path = tmp_path / "seat.log"
    logger = logging.getLogger("test.ansi.file_handler")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(ColoredFormatter("%(message)s", use_colors=False))
    logger.addHandler(handler)

    logger.info(COLORED_TABLE)
    handler.flush()
    handler.close()
    logger.handlers.clear()

    assert log_path.read_text(encoding="utf-8") == PLAIN_TABLE + "\n"
