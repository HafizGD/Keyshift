"""Tests for read-only diagnostics and private logging."""

import logging
import stat

import pytest

from keyshift import diagnostics
from keyshift.device_manager import DevicePermissionError
from keyshift.logging_config import configure_logging


def test_diagnostics_reports_missing_devices_and_uinput_as_warnings(tmp_path) -> None:
    results = diagnostics.run_diagnostics(
        keyboard_lister=lambda **kwargs: [],
        config_path=tmp_path / "missing.yaml",
        uinput_path=tmp_path / "missing-uinput",
        uinput_module_path=tmp_path / "missing-module",
        lock_checker=lambda: False,
    )
    by_name = {result.name: result for result in results}

    assert by_name["Input devices"].status == "WARN"
    assert by_name["uinput device"].status == "WARN"
    assert by_name["uinput module"].status == "WARN"
    assert by_name["Configuration"].status == "OK"


def test_diagnostics_explains_input_permission_failure(tmp_path) -> None:
    def denied(**kwargs):
        raise DevicePermissionError(["/dev/input/event7"])

    results = diagnostics.run_diagnostics(
        keyboard_lister=denied,
        config_path=tmp_path / "missing.yaml",
        uinput_path=tmp_path / "missing-uinput",
        uinput_module_path=tmp_path / "missing-module",
        lock_checker=lambda: False,
    )
    input_result = next(item for item in results if item.name == "Input devices")

    assert input_result.status == "WARN"
    assert "input" in input_result.detail
    assert "log out and back in" in input_result.detail


def test_diagnostics_reports_invalid_config_without_repairing_it(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("remaps: [", encoding="utf-8")

    results = diagnostics.run_diagnostics(
        keyboard_lister=lambda **kwargs: [],
        config_path=config_path,
        uinput_path=tmp_path / "missing-uinput",
        uinput_module_path=tmp_path / "missing-module",
        lock_checker=lambda: False,
    )
    config_result = next(item for item in results if item.name == "Configuration")

    assert config_result.status == "FAIL"
    assert config_path.read_text(encoding="utf-8") == "remaps: ["
    assert not config_path.with_suffix(".yaml.bak").exists()


def test_logging_is_private_and_reconfigures_without_duplicate_handlers(
    tmp_path,
) -> None:
    log_path = tmp_path / "logs" / "keyshift.log"
    configure_logging(debug=True, log_path=log_path)
    configure_logging(debug=True, log_path=log_path)
    logger = logging.getLogger("keyshift.test")
    logger.info("safe service summary")

    root_logger = logging.getLogger("keyshift")
    handlers = [
        handler
        for handler in root_logger.handlers
        if getattr(handler, "_keyshift_managed_handler", False)
    ]
    file_handler = next(
        handler
        for handler in handlers
        if getattr(handler, "baseFilename", None) == str(log_path)
    )
    file_handler.doRollover()

    assert len(handlers) == 2
    assert "safe service summary" in log_path.with_name(
        "keyshift.log.1"
    ).read_text(encoding="utf-8")
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_path.with_name("keyshift.log.1").stat().st_mode) == 0o600

    for handler in handlers:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(logging.NOTSET)
    root_logger.propagate = True
