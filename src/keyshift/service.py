"""Coordinate input listening, shortcuts, mappings, macros, and virtual output."""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Mapping
from types import FrameType
from typing import Any

from keyshift.config_manager import ConfigError, ConfigManager
from keyshift.device_manager import DeviceInfo, VIRTUAL_DEVICE_NAME
from keyshift.listener import KeyboardListener
from keyshift.macro_engine import MacroEngine, MacroExecutionError, MacroHandle
from keyshift.mapping_engine import MappingEngine
from keyshift.shortcut_manager import ShortcutManager
from keyshift.virtual_keyboard import VirtualKeyboard

logger = logging.getLogger("keyshift.service")


class ServiceError(RuntimeError):
    """Raised when the remapping service cannot safely start or run."""


class KeyshiftService:
    """Run the keyshift processing pipeline for one selected physical keyboard."""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        *,
        keyboard_factory: Callable[..., Any] = VirtualKeyboard,
        listener_factory: Callable[..., Any] = KeyboardListener,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.keyboard_factory = keyboard_factory
        self.listener_factory = listener_factory
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
        timeout: float | None = None,
        profile: str | None = None,
        debug: bool = False,
    ) -> None:
        """Start virtual output first, then listen/grab and process input."""
        if self._running:
            raise ServiceError("keyshift service is already running.")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        self._running = True
        self._device_info = device_info
        self._profile_override = profile
        output = self.keyboard_factory(
            name=VIRTUAL_DEVICE_NAME,
            source=device_info,
        )
        input_listener = None
        try:
            output.__enter__()
            self._output = output
            self._configure(self._load_config())
            self._macro_engine = MacroEngine(output)
            input_listener = self.listener_factory(device_info, grab=True)
            input_listener.__enter__()
            self._listener = input_listener
            self._install_sighup_handler()

            for event in input_listener.start(
                timeout=timeout,
                on_idle=self._reload_if_requested,
                close_on_finish=False,
            ):
                if debug:
                    logger.debug(
                        "input event %s value=%d code=%d",
                        event.name,
                        event.value,
                        event.code,
                    )
                self._process_event(event)
        finally:
            try:
                self._restore_sighup_handler()
            finally:
                try:
                    self._cancel_macros()
                finally:
                    try:
                        output.release_all()
                    finally:
                        try:
                            if input_listener is not None:
                                input_listener.stop()
                                input_listener.__exit__(None, None, None)
                        finally:
                            try:
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
                self._device_info.path if self._device_info is not None else state["selected_device"]
            ),
            "active_profile": self._profile_override or state["active_profile"],
            "remap_count": len(self._config.get("remaps", {})),
            "shortcut_count": len(self._config.get("shortcuts", {})),
            "macro_count": len(self._config.get("macros", {})),
        }

    def _load_config(self) -> dict[str, Any]:
        if self._profile_override:
            return self.config_manager.load_profile(self._profile_override)
        return self.config_manager.load_active_config()

    def _configure(self, config: dict[str, Any]) -> None:
        self._config = config
        self.mapping_engine = MappingEngine(config.get("remaps", {}))
        self.shortcut_manager = ShortcutManager(config.get("shortcuts", {}))
        self._macros = config.get("macros", {})

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

    def _process_event(self, event) -> None:
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

    def _handle_sighup(
        self, signum: int, frame: FrameType | None
    ) -> None:
        self._reload_requested.set()
