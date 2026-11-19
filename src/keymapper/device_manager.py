"""Discover and select physical keyboard input devices."""

import glob
from collections.abc import Callable, Iterable
from dataclasses import dataclass

VIRTUAL_DEVICE_NAME = "keymapper-virtual-keyboard"


@dataclass(frozen=True)
class DeviceInfo:
    """Basic information about a keyboard input device."""

    path: str
    name: str
    phys: str | None
    vendor: int
    product: int
    bustype: int


class DeviceError(Exception):
    """Base exception for device discovery and selection errors."""


class DeviceNotFoundError(DeviceError):
    """Raised when a device selector matches no keyboard."""


class AmbiguousDeviceError(DeviceError):
    """Raised when a device selector matches multiple keyboards."""


class DevicePermissionError(DeviceError):
    """Raised when keyboard devices cannot be read due to permissions."""

    def __init__(self, paths: Iterable[str]) -> None:
        self.paths = tuple(paths)
        super().__init__(
            "Permission denied while opening input device(s): "
            f"{', '.join(self.paths)}. Add your user to the 'input' group "
            "with 'sudo usermod -aG input $USER', then log out and back in."
        )


def list_keyboards(
    enumerator: Callable[[], Iterable[str]] | None = None,
    *,
    failed_devices: list[str] | None = None,
) -> list[DeviceInfo]:
    """Return readable keyboards, optionally using a test device enumerator.

    The optional ``failed_devices`` list receives paths that could not be
    inspected. Permission failures are raised only when no keyboard could be
    read, allowing other devices to remain usable.
    """
    import evdev

    if enumerator is None:
        paths = list(
            dict.fromkeys(
                [*evdev.list_devices(), *glob.glob("/dev/input/event*")]
            )
        )
    else:
        paths = enumerator()
    keyboards: list[DeviceInfo] = []
    failures: list[str] = []
    permission_failures: list[str] = []

    for path in paths:
        device = None
        try:
            device = evdev.InputDevice(path)
            if device.name == VIRTUAL_DEVICE_NAME:
                continue

            keys = device.capabilities().get(evdev.ecodes.EV_KEY, ())
            required_keys = (
                evdev.ecodes.KEY_A,
                evdev.ecodes.KEY_Z,
                evdev.ecodes.KEY_ENTER,
            )
            if not all(key in keys for key in required_keys):
                continue

            info = device.info
            keyboards.append(
                DeviceInfo(
                    path=device.path,
                    name=device.name,
                    phys=device.phys,
                    vendor=info.vendor,
                    product=info.product,
                    bustype=info.bustype,
                )
            )
        except PermissionError:
            failures.append(path)
            permission_failures.append(path)
        except OSError:
            failures.append(path)
        finally:
            if device is not None:
                try:
                    device.close()
                except OSError:
                    if path not in failures:
                        failures.append(path)

    if failed_devices is not None:
        failed_devices.extend(failures)
    if not keyboards and permission_failures:
        raise DevicePermissionError(permission_failures)
    return keyboards


def find_device(
    selector: str,
    enumerator: Callable[[], Iterable[str]] | None = None,
) -> DeviceInfo:
    """Find a keyboard by exact path, one-based list number, or name fragment."""
    devices = list_keyboards(enumerator)

    path_matches = [device for device in devices if device.path == selector]
    if path_matches:
        return path_matches[0]
    if selector.startswith("/"):
        raise DeviceNotFoundError(f"No keyboard found at path '{selector}'.")

    if selector.isdecimal():
        number = int(selector)
        if 1 <= number <= len(devices):
            return devices[number - 1]
        raise DeviceNotFoundError(
            f"No keyboard at list number {number}; choose a number from 1 to "
            f"{len(devices)}."
        )

    normalized_selector = selector.casefold()
    matches = [
        device
        for device in devices
        if normalized_selector in device.name.casefold()
    ]
    if not matches:
        raise DeviceNotFoundError(
            f"No keyboard matched path, list number, or name '{selector}'."
        )
    if len(matches) > 1:
        names = ", ".join(
            f"'{device.name}' ({device.path})" for device in matches
        )
        raise AmbiguousDeviceError(
            f"Selector '{selector}' matched multiple keyboards: {names}. "
            "Use a device path or list number."
        )
    return matches[0]
