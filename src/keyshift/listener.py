"""Read keyboard key events from Linux input devices."""

from __future__ import annotations

import errno
import select
import signal
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from types import FrameType

from keyshift.device_manager import (
    DeviceError,
    DeviceInfo,
    DevicePermissionError,
    VIRTUAL_DEVICE_NAME,
)


@dataclass(frozen=True)
class KeyEvent:
    """A normalized keyboard key event."""

    code: int
    name: str
    value: int
    timestamp: float


class DeviceDisconnectedError(DeviceError):
    """Raised when an input device disappears while being monitored."""


class KeyboardListener:
    """Read EV_KEY events, optionally grabbing a device exclusively.

    The default is observational and does not grab the physical device. When
    ``grab=True``, callers are responsible for providing an emergency exit and
    a finite timeout before running it against a physical keyboard.
    """

    def __init__(self, device_info: DeviceInfo, grab: bool = False) -> None:
        self.device_info = device_info
        self.grab = grab
        self._device = None
        self._evdev = None
        self._grabbed = False
        self._running = False
        self._stop_requested = threading.Event()
        self._sigterm_handler_installed = False
        self._previous_sigterm_handler = None

    def __enter__(self) -> KeyboardListener:
        self._open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.stop()
        return False

    def __iter__(self) -> Iterator[KeyEvent]:
        return self.start()

    def start(
        self,
        callback: Callable[[KeyEvent], None] | None = None,
        *,
        timeout: float | None = None,
        on_idle: Callable[[], None] | None = None,
        close_on_finish: bool = True,
    ) -> Iterator[KeyEvent]:
        """Return an event iterator; optionally invoke ``callback`` per event."""
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        return self._iter_events(callback, timeout, on_idle, close_on_finish)

    def stop(self) -> None:
        """Request the event loop to stop and release/close the device."""
        self._stop_requested.set()
        self._cleanup()

    def _open(self) -> None:
        if self._device is not None:
            return
        if self.device_info.name == VIRTUAL_DEVICE_NAME:
            raise DeviceError(
                f"Ignoring virtual keyboard '{VIRTUAL_DEVICE_NAME}'."
            )

        import evdev

        self._evdev = evdev
        try:
            device = evdev.InputDevice(self.device_info.path)
        except PermissionError as error:
            raise DevicePermissionError([self.device_info.path]) from error
        except OSError as error:
            if error.errno == errno.ENODEV:
                raise DeviceDisconnectedError(
                    f"Input device '{self.device_info.path}' is unavailable."
                ) from error
            raise

        if device.name == VIRTUAL_DEVICE_NAME:
            device.close()
            raise DeviceError(
                f"Ignoring virtual keyboard '{VIRTUAL_DEVICE_NAME}'."
            )
        self._device = device

    def _iter_events(
        self,
        callback: Callable[[KeyEvent], None] | None,
        timeout: float | None,
        on_idle: Callable[[], None] | None,
        close_on_finish: bool,
    ) -> Iterator[KeyEvent]:
        self._open()
        if self._running:
            raise DeviceError("This keyboard listener is already running.")

        self._stop_requested.clear()
        self._running = True
        try:
            self._install_sigterm_handler()
            self._grab_device()
            for raw_event in self._read_events(timeout, on_idle):
                if self._stop_requested.is_set():
                    break
                if raw_event.type != self._evdev.ecodes.EV_KEY:
                    continue

                event = self._normalize_event(raw_event)
                if callback is not None:
                    callback(event)
                yield event
        except KeyboardInterrupt:
            self._stop_requested.set()
        except OSError as error:
            if error.errno == errno.ENODEV:
                raise DeviceDisconnectedError(
                    f"Input device '{self.device_info.path}' was disconnected."
                ) from error
            raise
        finally:
            self._running = False
            try:
                self._restore_sigterm_handler()
            finally:
                if close_on_finish:
                    self._cleanup()

    def _read_events(
        self,
        timeout: float | None,
        on_idle: Callable[[], None] | None,
    ) -> Iterator[object]:
        device = self._device
        if device is None:
            return

        fd = getattr(device, "fd", None)
        if fd is None:
            yield from device.read_loop()
            return

        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._stop_requested.is_set():
            wait = 0.2
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                wait = min(wait, remaining)
            try:
                readable, _, _ = select.select([fd], [], [], wait)
            except OSError:
                if self._stop_requested.is_set():
                    break
                raise
            if readable:
                yield from device.read()
            elif on_idle is not None:
                on_idle()

    def _normalize_event(self, raw_event: object) -> KeyEvent:
        code = raw_event.code
        name = self._evdev.ecodes.KEY.get(code, f"KEY_{code}")
        if isinstance(name, (list, tuple)):
            name = name[0] if name else f"KEY_{code}"
        return KeyEvent(
            code=code,
            name=name,
            value=raw_event.value,
            timestamp=raw_event.sec + raw_event.usec / 1_000_000,
        )

    def _grab_device(self) -> None:
        if not self.grab or self._grabbed:
            return
        try:
            self._device.grab()
        except PermissionError as error:
            raise DevicePermissionError([self.device_info.path]) from error
        except OSError as error:
            if error.errno == errno.ENODEV:
                raise DeviceDisconnectedError(
                    f"Input device '{self.device_info.path}' was disconnected."
                ) from error
            raise
        self._grabbed = True

    def _cleanup(self) -> None:
        device = self._device
        if device is None:
            return

        cleanup_error = None
        try:
            if self._grabbed:
                try:
                    device.ungrab()
                except OSError as error:
                    if error.errno != errno.ENODEV:
                        cleanup_error = error
        finally:
            self._grabbed = False
            try:
                device.close()
            except OSError as error:
                if error.errno != errno.ENODEV and cleanup_error is None:
                    cleanup_error = error
            finally:
                self._device = None

        if cleanup_error is not None:
            raise cleanup_error

    def _install_sigterm_handler(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        self._sigterm_handler_installed = True

    def _restore_sigterm_handler(self) -> None:
        if self._sigterm_handler_installed:
            signal.signal(signal.SIGTERM, self._previous_sigterm_handler)
            self._sigterm_handler_installed = False

    def _handle_sigterm(
        self, signum: int, frame: FrameType | None
    ) -> None:
        self._stop_requested.set()
        raise KeyboardInterrupt
