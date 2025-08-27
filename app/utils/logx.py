# app/utils/logx.py
from __future__ import annotations
import inspect
import logging
from typing import Any


def get_logger(name: str) -> logging.Logger:
    """
    Створює logger із вказаним ім'ям.
    Використовуй цей метод замість logging.getLogger(name) напряму.
    """
    return logging.getLogger(name)


def _format_msg(msg: str) -> str:
    """
    Додає інформацію про файл і функцію, звідки викликано лог.
    """
    frame = inspect.stack()[2]  # беремо рівень вище виклику logx
    filename = frame.filename.split("/")[-1]
    funcname = frame.function
    lineno = frame.lineno
    return f"[{filename}:{funcname}:{lineno}] {msg}"


def debug(logger: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    logger.debug(_format_msg(msg), *args, **kwargs)


def info(logger: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    logger.info(_format_msg(msg), *args, **kwargs)


def warning(logger: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    logger.warning(_format_msg(msg), *args, **kwargs)


def error(logger: logging.Logger, msg: str, *args: Any, **kwargs: Any) -> None:
    logger.error(_format_msg(msg), *args, **kwargs)