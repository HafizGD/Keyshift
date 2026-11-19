"""Coordinate input listening, shortcuts, mappings, macros, and virtual output."""

from __future__ import annotations

import fcntl
import logging
import math
import os
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any

from keyshift import device_manager
from keyshift.config_manager import ConfigError, ConfigManager
from keyshift.device_manager import DeviceInfo, VIRTUAL_DEVICE_NAME
from keyshift.listener import (
    DeviceDisconnectedError,
    KeyEvent,
    KeyboardListener,
)
from keyshift.macro_engine import MacroEngine, MacroExecutionError, MacroHandle
from keyshift.mapping_engine import (
    MappingEngine,
    TemporaryMappingManager,
    resolve_key,
)
from keyshift.shortcut_manager import ShortcutManager
from keyshift.virtual_keyboard import VirtualKeyboard

logger = logging.getLogger("keyshift.service")


class ServiceError(RuntimeError):
    """Raised when the remapping service cannot safely start or run."""


class ProcessLock:
    """Prevent concurrent keyshift services using a non-blocking file lock."""

    def __init__(self, path: Path | None = None) -> None:
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        if not state_home.is_absolute():
            state_home = Path.home() / ".local/state"
        self.path = path or state_home / "keyshift" / "service.lock"
        self._file = None

    def __enter__(self) -> ProcessLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise ServiceError(
                f"Another keyshift service is already running (lock: {self.path})."
            ) from error
        except OSError:
            handle.close()
            raise
        self._file = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n")
            handle.flush()
        except OSError:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._file is not None:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None
        return False

    @staticmethod
    def is_locked(path: Path | None = None) -> bool:
        """Check lock state without waiting for the running service."""
        if path is None:
            state_home = Path(
                os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")
            )
            if not state_home.is_absolute():
                state_home = Path.home() / ".local/state"
            path = state_home / "keyshift" / "service.lock"
        try:
            handle = path.open("r+", encoding="utf-8")
        except FileNotFoundError:
            return False
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return False
        finally:
            handle.close()


class _EmergencyExitTriggered(Exception):
    """Stop the service after the configured physical-key hold chord."""


class EmergencyExitDetector:
    """Buffer a safety chord and recognize it only after a sustained hold."""

    def __init__(
        self,
        combination: str,
        *,
        hold_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        keys = [resolve_key(part.strip()) for part in combination.split("+")]
        if len(keys) < 2 or len(keys) > 8 or len(set(keys)) != len(keys):
            raise ValueError("Emergency exit must contain 2 to 8 unique keys.")
        if not math.isfinite(hold_seconds) or hold_seconds <= 0:
            raise ValueError("Emergency hold duration must be greater than zero.")
        self._keys = frozenset(keys)
        self._hold_seconds = hold_seconds
        self._clock = clock
        self._pressed: set[int] = set()
        self._pending: list[KeyEvent] = []
        self._candidate_since: float | None = None
        self._hold_since: float | None = None

    def process(
        self,
        event: KeyEvent,
    ) -> tuple[bool, bool, tuple[KeyEvent, ...]]:
        """Return (triggered, buffered, events-to-forward) for one event."""
        self._update_pressed(event)
        if self._pending:
            self._pending.append(event)
            if self._is_complete():
                if self._hold_since is None:
                    self._hold_since = self._clock()
                if self._clock() - self._hold_since >= self._hold_seconds:
                    self._clear_pending()
                    return True, False, ()
                return False, True, ()
            self._hold_since = None
            if (
                self._candidate_since is not None
                and self._clock() - self._candidate_since >= self._hold_seconds
            ):
                return False, False, self._flush()
            if event.code not in self._keys or event.value == 0:
                return False, False, self._flush()
            return False, True, ()

        if (
            event.value == 1
            and event.code in self._keys
            and self._pressed <= self._keys
        ):
            now = self._clock()
            self._pending = [event]
            self._candidate_since = now
            if self._is_complete():
                self._hold_since = now
            return False, True, ()
        return False, False, (event,)

    def check_timeout(self) -> tuple[bool, tuple[KeyEvent, ...]]:
        """Trigger a held full chord or flush an incomplete candidate safely."""
        if not self._pending or self._candidate_since is None:
            return False, ()
        now = self._clock()
        if (
            self._hold_since is not None
            and now - self._hold_since >= self._hold_seconds
        ):
            self._clear_pending()
            return True, ()
        if (
            self._hold_since is None
            and now - self._candidate_since >= self._hold_seconds
        ):
            return False, self._flush()
        return False, ()

    def _update_pressed(self, event: KeyEvent) -> None:
        if event.value == 1:
            self._pressed.add(event.code)
        elif event.value == 0:
            self._pressed.discard(event.code)

    def _is_complete(self) -> bool:
        return self._keys <= self._pressed and self._pressed <= self._keys

    def _flush(self) -> tuple[KeyEvent, ...]:
        pending = tuple(self._pending)
        self._clear_pending()
        return pending

    def _clear_pending(self) -> None:
        self._pending.clear()
        self._candidate_since = None
        self._hold_since = None


class KeyshiftService:
    """Run the keyshift processing pipeline for one selected physical keyboard."""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        *,
        keyboard_factory: Callable[..., Any] = VirtualKeyboard,
        listener_factory: Callable[..., Any] = KeyboardListener,
        lock_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.keyboard_factory = keyboard_factory
        self.listener_factory = listener_factory
        self.lock_path = lock_path
        self._clock = clock
        self._sleep = sleeper
        self._running = False
        self._device_info: DeviceInfo | None = None
        self._output = None
        self._listener = None
        self._macro_engine: MacroEngine | None = None
        self._macro_handles: list[MacroHandle] = []
        self._profile_override: str | None = None
        self._config: dict[str, Any] = {}
        self._reload_requested = threading.Event()
        self._previous_sighup_handler = None
        self._sighup_handler_installed = False

    def run(
        self,
        device_info: DeviceInfo,
        *,
        timeout: float | None,
        profile: str | None = None,
        debug: bool = False,
        reconnect: bool = False,
    ) -> None:
        """Run with a finite safety timeout, releasing output on every exit."""
        if self._running:
            raise ServiceError("keyshift service is already running.")
        if timeout is None or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("A finite timeout greater than zero is required.")

        self._running = True
        self._device_info = device_info
        self._profile_override = profile
        output = None
        try:
            with ProcessLock(self.lock_path):
                try:
                    output = self.keyboard_factory(
                        name=VIRTUAL_DEVICE_NAME,
                        source=device_info,
                    )
                    self._output = output
                    output.__enter__()
                    self._configure(self._load_config())
                    self._macro_engine = MacroEngine(output)
                    self._install_sighup_handler()

                    deadline = self._clock() + timeout
                    selected = device_info
                    while True:
                        remaining = deadline - self._clock()
                        if remaining <= 0:
                            break
                        try:
                            self._run_listener(selected, remaining, debug)
                            break
                        except DeviceDisconnectedError:
                            if not reconnect:
                                raise
                            logger.warning(
                                "Input device %s disconnected; waiting to reconnect.",
                                selected.path,
                            )
                            self.mapping_engine.reset_held_keys()
                            self.temporary_mapping_manager.reset_held_state()
                            self._output.release_all()
                            selected = self._wait_for_reconnect(selected, deadline)
                            if selected is None:
                                logger.info("Service timeout elapsed while reconnecting.")
                                break
                            self._device_info = selected
                except _EmergencyExitTriggered:
                    logger.info(
                        "Emergency exit chord held; stopping keyshift safely."
                    )
                finally:
                    try:
                        self._restore_sighup_handler()
                    finally:
                        try:
                            self._cancel_macros()
                        finally:
                            try:
                                if output is not None and self._output is not None:
                                    output.release_all()
                            finally:
                                if output is not None:
                                    output.close()
        finally:
            self._running = False
            self._device_info = None
            self._output = None
            self._listener = None
            self._macro_engine = None
            self._profile_override = None

    def status(self) -> dict[str, object]:
        """Return in-process service state and the selected configuration."""
        state = self.config_manager.load_state()
        return {
            "running": self._running,
            "device": (
                self._device_info.path
                if self._device_info is not None
                else state["selected_device"]
            ),
            "active_profile": self._profile_override or state["active_profile"],
            "remap_count": len(self._config.get("remaps", {})),
            "temporary_mapping_count": len(
                self._config.get("temporary_mappings", [])
            ),
            "shortcut_count": len(self._config.get("shortcuts", {})),
            "macro_count": len(self._config.get("macros", {})),
        }

    def _run_listener(
        self,
        device_info: DeviceInfo,
        timeout: float,
        debug: bool,
    ) -> None:
        input_listener = self.listener_factory(device_info, grab=True)
        entered = False
        try:
            input_listener.__enter__()
            entered = True
            self._listener = input_listener
            for event in input_listener.start(
                timeout=timeout,
                on_idle=self._on_idle,
                close_on_finish=False,
            ):
                if debug:
                    logger.debug(
                        "input event %s value=%d code=%d",
                        event.name,
                        event.value,
                        event.code,
                    )
                triggered, buffered, events = (
                    self.emergency_exit_detector.process(event)
                )
                if triggered:
                    raise _EmergencyExitTriggered
                if buffered:
                    continue
                for ready_event in events:
                    self._process_pipeline_event(ready_event)
        finally:
            try:
                self._output.release_all()
            finally:
                try:
                    input_listener.stop()
                finally:
                    if entered:
                        input_listener.__exit__(None, None, None)
                    self._listener = None

    def _wait_for_reconnect(
        self,
        original: DeviceInfo,
        deadline: float,
    ) -> DeviceInfo | None:
        while self._clock() < deadline:
            self._on_idle()
            devices = device_manager.list_keyboards()
            if original.phys:
                matches = [item for item in devices if item.phys == original.phys]
            else:
                matches = [
                    item
                    for item in devices
                    if (
                        item.vendor,
                        item.product,
                        item.name,
                    )
                    == (original.vendor, original.product, original.name)
                ]
            if len(matches) == 1:
                return matches[0]
            self._sleep(min(0.25, max(0.0, deadline - self._clock())))
        return None

    def _load_config(self) -> dict[str, Any]:
        if self._profile_override:
            return self.config_manager.load_profile(self._profile_override)
        return self.config_manager.load_active_config()

    def _configure(self, config: dict[str, Any]) -> None:
        self._config = config
        existing_mapping_engine = getattr(self, "mapping_engine", None)
        if existing_mapping_engine is None:
            self.mapping_engine = MappingEngine(config.get("remaps", {}))
        else:
            existing_mapping_engine.set_mappings(config.get("remaps", {}))
            self.mapping_engine = existing_mapping_engine
        self.temporary_mapping_manager = TemporaryMappingManager(
            config.get("temporary_mappings", []),
            clock=self._clock,
        )
        self.mapping_engine.set_temporary_mappings(
            self.temporary_mapping_manager.active_mappings()
        )
        self.shortcut_manager = ShortcutManager(config.get("shortcuts", {}))
        self.emergency_exit_detector = EmergencyExitDetector(
            config.get("emergency_exit", "LeftCtrl+LeftAlt+LeftShift+Esc"),
            clock=self._clock,
        )
        self._macros = config.get("macros", {})

    def _on_idle(self) -> None:
        self._reload_if_requested()
        triggered, events = self.emergency_exit_detector.check_timeout()
        if triggered:
            raise _EmergencyExitTriggered
        for event in events:
            self._process_pipeline_event(event)
        self.mapping_engine.set_temporary_mappings(
            self.temporary_mapping_manager.active_mappings()
        )

    def _reload_if_requested(self) -> None:
        if not self._reload_requested.is_set():
            return
        self._reload_requested.clear()
        try:
            self._configure(self._load_config())
        except ConfigError:
            logger.exception("Could not reload keyshift configuration")
            return
        logger.info("Reloaded keyshift configuration")

    def _process_pipeline_event(self, event: KeyEvent) -> None:
        consumed = self.temporary_mapping_manager.process(event)
        self.mapping_engine.set_temporary_mappings(
            self.temporary_mapping_manager.active_mappings()
        )
        if consumed:
            return
        shortcut = self.shortcut_manager.process(event)
        if shortcut.matched and shortcut.action:
            self._run_action(shortcut.action)
        if shortcut.buffered:
            if shortcut.events:
                self._send_events(shortcut.events)
            return
        self._send_events(shortcut.events)

    def _send_events(self, events) -> None:
        for event in events:
            for mapped in self.mapping_engine.process(event):
                self._output.emit(mapped.code, mapped.value)

    def _run_action(self, action: str) -> None:
        if action.startswith("macro:"):
            name = action.removeprefix("macro:")
            steps = self._macros.get(name)
            if steps is None:
                raise ConfigError(f"Shortcut references unknown macro '{name}'.")
            self._macro_handles.append(self._macro_engine.play(name, steps))
            return
        if action.startswith("profile:"):
            name = action.removeprefix("profile:")
            config = self.config_manager.activate_profile(name)
            self._profile_override = None
            self._configure(config)
            return
        raise ConfigError(
            f"Unsupported shortcut action '{action}'. "
            "Use 'macro:<name>' or 'profile:<name>'."
        )

    def _cancel_macros(self) -> None:
        execution_error = None
        for handle in self._macro_handles:
            handle.cancel()
            try:
                handle.join()
            except MacroExecutionError as error:
                if execution_error is None:
                    execution_error = error
        self._macro_handles.clear()
        if execution_error is not None:
            raise execution_error

    def _install_sighup_handler(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._previous_sighup_handler = signal.getsignal(signal.SIGHUP)
        signal.signal(signal.SIGHUP, self._handle_sighup)
        self._sighup_handler_installed = True

    def _restore_sighup_handler(self) -> None:
        if self._sighup_handler_installed:
            signal.signal(signal.SIGHUP, self._previous_sighup_handler)
            self._sighup_handler_installed = False

    def _handle_sighup(self, signum: int, frame: FrameType | None) -> None:
        self._reload_requested.set()
