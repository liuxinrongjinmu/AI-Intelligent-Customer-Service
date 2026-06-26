"""
结构化 JSON 日志格式化器

生产环境使用 JSON 格式输出日志，便于日志检索和过滤。
开发环境保持人类可读的文本格式。
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """
    JSON 日志格式化器

    将日志记录转换为 JSON 格式，包含：
    - timestamp: ISO 8601 时间戳
    - level: 日志级别
    - logger: 日志器名称
    - message: 日志消息
    - module: 模块名
    - line: 行号
    - request_id: 请求链路ID（如有）
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为 JSON 字符串

        :param record: 日志记录对象
        :return: JSON 格式的日志字符串
        """
        # 尝试获取 request_id（从 ContextVar）
        try:
            from backend.utils.request_id import get_request_id
            request_id = get_request_id()
        except Exception:
            request_id = ""

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }

        if request_id:
            log_entry["request_id"] = request_id

        # 异常信息
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 额外字段（通过 logger.info("msg", extra={...}) 传入）
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                try:
                    json.dumps(value)
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(env: str = "dev"):
    """
    根据环境配置日志格式

    :param env: 环境名称（dev/prod）
    """
    root_logger = logging.getLogger()

    # 清除已有 handler
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)

    if env == "prod":
        # 生产环境：JSON 格式
        handler.setFormatter(JsonFormatter())
        root_logger.setLevel(logging.INFO)
    else:
        # 开发环境：人类可读格式
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        root_logger.setLevel(logging.DEBUG)

    root_logger.addHandler(handler)

    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
