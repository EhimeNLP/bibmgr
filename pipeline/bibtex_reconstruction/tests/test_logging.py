from __future__ import annotations

import logging

from bibtex_reconstruction.logging_config import (
    PACKAGE_LOGGER_NAME,
    configure_logging,
)


def test_detailed_log_includes_debug_context(tmp_path):
    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    original_handlers = package_logger.handlers[:]
    original_level = package_logger.level
    original_propagate = package_logger.propagate
    log_path = tmp_path / "logs" / "reconstruction.log"

    try:
        configure_logging(console_level="ERROR", log_file=log_path)
        logging.getLogger(f"{PACKAGE_LOGGER_NAME}.test").debug(
            "API search completed ref_id=b0 status=match"
        )

        for handler in package_logger.handlers:
            handler.flush()

        contents = log_path.read_text(encoding="utf-8")
        assert "DEBUG" in contents
        assert "bibtex_reconstruction.test" in contents
        assert "ref_id=b0 status=match" in contents
    finally:
        for handler in package_logger.handlers:
            handler.close()
        package_logger.handlers = original_handlers
        package_logger.setLevel(original_level)
        package_logger.propagate = original_propagate
