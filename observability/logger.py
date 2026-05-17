"""
Centralized logging setup and logger access.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

_LOGGER_INITIALIZED = False


def setup_logger(
    log_path: str,
    level: int | str = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    fmt: Optional[str] = None,
) -> None:
    global _LOGGER_INITIALIZED
    if _LOGGER_INITIALIZED:
        return

    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    log_format = fmt or "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(log_format)

    resolved_level = level
    if isinstance(level, str):
        resolved_level = logging.getLevelName(level.upper())
        if isinstance(resolved_level, str):
            resolved_level = logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    if root_logger.handlers:
        root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(resolved_level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(resolved_level)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    _LOGGER_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# noinspection PyUnusedLocal
class PrintLogger:
    @staticmethod
    def info(message: str, *args, **kwargs) -> None:
        print(f"[INFO] {message}")

    @staticmethod
    def warning(message: str, *args, **kwargs) -> None:
        print(f"[WARNING] {message}")

    @staticmethod
    def error(message: str, *args, **kwargs) -> None:
        print(f"[ERROR] {message}")

    @staticmethod
    def exception(message: str, *args, **kwargs) -> None:
        print(f"[EXCEPTION] {message}")
