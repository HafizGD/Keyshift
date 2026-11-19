# keyshift

`keyshift` is a Python library and CLI scaffold for keyboard input remapping on
Linux. It currently supports physical keyboard discovery, event monitoring,
and standalone key mapping, shortcut, and virtual keyboard components. The full
remapping service is not connected yet.

## Requirements

- Linux with Python 3.10 or newer
- Access to keyboard input devices for future hardware features

Device permissions, desktop environments, and keyboard capabilities vary.
Compatibility with every keyboard or desktop environment is not guaranteed.
Future input handling must provide an emergency reset and avoid leaving
physical input devices grabbed.

Reading `/dev/input/event*` devices can expose all keystrokes, including
passwords. Only grant the `input` group to trusted users, and do not run
untrusted code as a user in that group. Group membership takes effect after
logging out and back in.

## Development setup

```shell
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

## CLI

```shell
keyshift --version
keyshift --help
keyshift list-devices
keyshift monitor --timeout 15
```

`list-devices` reports readable keyboard devices and accepts `--json` for JSON
output. `monitor` prints key press, release, and repeat events without grabbing
the device; use `--device` to select by path, list number, or name fragment.
It accepts a timeout so observation ends automatically. It filters event nodes
by key capabilities; some keyboards (including Bluetooth, KVM, remote desktop,
and multi-node devices) may expose different capabilities or may not be
discoverable as expected.

The listener can optionally grab a device through its library API, which
prevents the desktop from receiving those physical events. The CLI monitor
never enables grab. Do not use grab mode until an emergency exit and automatic
timeout are active, and arrange a backup keyboard or SSH/TTY access first.

The `VirtualKeyboard` library API writes output through `/dev/uinput` and
releases held keys when closed. It is not yet connected to a remapping command.
To prepare uinput access, load the module (`sudo modprobe uinput`) and install
a udev rule assigning `/dev/uinput` to group `input` with mode `0660`; log out
and back in after changing group membership.

Shortcut triggers and outputs are based on Linux key codes, not translated
characters; their behavior therefore depends on the active keyboard layout.
The shortcut component is not yet connected to the CLI service.

`MacroEngine` can execute validated key-down, key-up, tap, delay, and simple
ASCII text steps in a worker thread. It bounds step count and total delay,
supports cancellation, and sends output directly to its output sink rather
than back through the mapping engine. Text key positions use a basic US layout;
this is not a character-layout translation service.

Configuration uses YAML under `~/.config/keyshift/` (or
`$XDG_CONFIG_HOME/keyshift/`): `config.yaml`, `state.yaml`, and
`profiles/<name>.yaml`. Writes are atomic. Invalid files are preserved as
`.bak` files, reset to defaults, and reported with a recovery warning.

## Package layout

- `src/keyshift/device_manager.py`: keyboard device discovery and selection
- `src/keyshift/listener.py`: input event reading
- `src/keyshift/mapping_engine.py`: key remapping
- `src/keyshift/shortcut_manager.py`: shortcut mapping
- `src/keyshift/macro_engine.py`: macro execution
- `src/keyshift/virtual_keyboard.py`: virtual keyboard output
- `src/keyshift/config_manager.py`: configuration and profiles
- `src/keyshift/cli.py`: Typer command-line interface
- `configs/default.yaml`: starter configuration
