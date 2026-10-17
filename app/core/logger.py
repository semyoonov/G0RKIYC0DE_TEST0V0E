import logging
import sys

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_NOISY_LOGGERS = (
    "aiogram",
    "asyncio",
    "httpx",
    "httpcore",
    "sqlalchemy.engine",
    "uvicorn.access",
)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
