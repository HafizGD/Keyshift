"""Configure private, rotating logs for keyshift."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


_HANDLER_MARKER = "_keyshift_managed_handler"


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Keep the active and rotated log files readable only by the owner."""

    def _open(self):
        stream = super()._open()
        os.fchmod(stream.fileno(), 0o600)
        return stream


def default_log_path() -> Path:
    """Return the XDG state location used for keyshift logs."""
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    if not state_home.is_absolute():
        state_home = Path.home() / ".local/state"
    return state_home / "keyshift" / "keyshift.log"


def configure_logging(
    *,
    debug: bool = False,
    log_path: Path | None = None,
) -> Path:
    """Set up stderr and rotating-file logs without recording key contents."""
    path = log_path or default_log_path()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if log_path is None:
        path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    path.chmod(0o600)

    logger = logging.getLogger("keyshift")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    file_handler = _PrivateRotatingFileHandler(
        path,
        maxBytes=1_048_576,
        backupCount=3,
        encoding="utf-8",
    )
    stream_handler = logging.StreamHandler()
    for handler in (file_handler, stream_handler):
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return path
