"""Send keyboard events through a Linux uinput device."""

from __future__ import annotations

import threading

from keyshift.device_manager import DeviceError, DeviceInfo, VIRTUAL_DEVICE_NAME


class UinputPermissionError(DeviceError):
    """Raised when the virtual input device cannot be created."""

    def __init__(self, error: OSError) -> None:
        super().__init__(
            f"Cannot create a virtual keyboard via /dev/uinput: {error}. "
            "Check that uinput is available and that your account has access "
            "to /dev/uinput."
        )


class VirtualKeyboard:
    """Create and write to a virtual keyboard, releasing held keys on close."""

    def __init__(
        self,
        name: str = VIRTUAL_DEVICE_NAME,
        source: DeviceInfo | str | None = None,
    ) -> None:
        self.name = name
        self.source = source
        self._uinput = None
        self._evdev = None
        self._held_keys: dict[int, None] = {}
        self._lock = threading.RLock()

    def __enter__(self) -> VirtualKeyboard:
        self._open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def press(self, code: int) -> None:
        """Press a key once; repeated calls while held do not duplicate it."""
        with self._lock:
            self._ensure_open()
            if code not in self._held_keys:
                self.emit(code, 1)

    def release(self, code: int) -> None:
        """Release a key previously pressed by this virtual keyboard."""
        with self._lock:
            self._ensure_open()
            if code in self._held_keys:
                self.emit(code, 0)

    def tap(self, code: int) -> None:
        """Press and release a key."""
        with self._lock:
            self.press(code)
            self.release(code)

    def emit(self, code: int, value: int) -> None:
        """Emit an EV_KEY event with a Linux key value (0, 1, or 2)."""
        if value not in (0, 1, 2):
            raise ValueError("key event value must be 0 (release), 1 (press), or 2 (repeat)")
        with self._lock:
            self._ensure_open()
            self._uinput.write(self._evdev.ecodes.EV_KEY, code, value)
            self._uinput.syn()
            if value == 1:
                self._held_keys[code] = None
            elif value == 0:
                self._held_keys.pop(code, None)

    def syn(self) -> None:
        """Flush pending virtual input events to the kernel."""
        with self._lock:
            self._ensure_open()
            self._uinput.syn()

    def release_all(self) -> None:
        """Release every key held by this virtual keyboard."""
        with self._lock:
            if self._uinput is None:
                self._held_keys.clear()
                return
            if not self._held_keys:
                return

            for code in self._held_keys:
                self._uinput.write(self._evdev.ecodes.EV_KEY, code, 0)
            self._uinput.syn()
            self._held_keys.clear()

    def close(self) -> None:
        """Release held keys and destroy the virtual input device."""
        with self._lock:
            if self._uinput is None:
                return
            uinput = self._uinput
            try:
                self.release_all()
            finally:
                self._held_keys.clear()
                self._uinput = None
                uinput.close()

    def _ensure_open(self) -> None:
        if self._uinput is None:
            self._open()

    def _open(self) -> None:
        if self._uinput is not None:
            return

        import evdev

        self._evdev = evdev
        events = self._get_capabilities(evdev)
        try:
            self._uinput = evdev.UInput(events=events, name=self.name)
        except OSError as error:
            raise UinputPermissionError(error) from error

    def _get_capabilities(self, evdev) -> dict[int, list[int]]:
        if self.source is None:
            key_codes = sorted(
                code
                for code in evdev.ecodes.KEY
                if isinstance(code, int) and code > 0
            )
            return {evdev.ecodes.EV_KEY: key_codes}

        source_device = None
        if isinstance(self.source, DeviceInfo):
            source_path = self.source.path
        else:
            source_path = self.source
        source_device = evdev.InputDevice(source_path)
        try:
            capabilities = source_device.capabilities()
            return {
                event_type: codes
                for event_type, codes in capabilities.items()
                if event_type != evdev.ecodes.EV_SYN
            }
        finally:
            source_device.close()
