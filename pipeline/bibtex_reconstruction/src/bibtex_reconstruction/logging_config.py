"""Logging configuration for interactive and unattended CLI runs."""

from __future__ import annotations

import logging
from pathlib import Path


PACKAGE_LOGGER_NAME = "bibtex_reconstruction"


def configure_logging(
    *,
    console_level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Configure concise console output and an optional detailed log file."""

    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    package_logger.setLevel(logging.DEBUG)
    package_logger.propagate = False

    for handler in package_logger.handlers:
        handler.close()
    package_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level.upper())
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    package_logger.addHandler(console_handler)

    if log_file is None:
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            (
                "%(asctime)s.%(msecs)03d | %(levelname)-7s | "
                "%(threadName)s | %(name)s | %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    package_logger.addHandler(file_handler)
