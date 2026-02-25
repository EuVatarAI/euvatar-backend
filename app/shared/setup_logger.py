import logging
import os
import sys
from typing import Optional

from app.shared.trace import get_trace_id


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True


class LoggerManager:
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self.logger = logging.getLogger("euvatar")
        self.logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        self._configure_root_logger()

    def _configure_root_logger(self) -> None:
        root_logger = logging.getLogger()
        if getattr(root_logger, "_euvatar_logger_configured", False):
            return
        root_logger.handlers = []
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s trace_id=%(trace_id)s %(message)s"
        )
        handler.setFormatter(formatter)
        handler.addFilter(TraceIdFilter())
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        root_logger._euvatar_logger_configured = True  # type: ignore[attr-defined]

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        if not name:
            return self.logger
        return logging.getLogger(name)

    def log_info(self, message: str) -> None:
        self.logger.info(message)

    def log_debug(self, message: str) -> None:
        if self.debug:
            self.logger.debug(message)

    def log_error(self, message: str) -> None:
        self.logger.error(message)

    def log_warning(self, message: str) -> None:
        self.logger.warning(message)


def is_debug_enabled() -> bool:
    return os.getenv("APP_DEBUG", "false").lower() == "true"


LOGGER = LoggerManager(debug=is_debug_enabled())
