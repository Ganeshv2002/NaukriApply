from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .storage import LocalStore


LOGGER_NAME = "naukri_assistant"


def configure_logging(store: LocalStore) -> logging.Logger:
    store.ensure_layout()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = store.logs_dir / "naukri-assistant.log"
    existing_files = {
        getattr(handler, "baseFilename", None)
        for handler in logger.handlers
    }
    if str(log_path) not in existing_files:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(file_handler)
    return logger

