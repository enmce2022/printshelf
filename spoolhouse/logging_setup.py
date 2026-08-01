from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUP_COUNT = 3

_configured = False


def configure_logging(data_dir: Path, *, level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "spoolhouse.log"

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    root = logging.getLogger("spoolhouse")
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.propagate = False

    _configured = True
