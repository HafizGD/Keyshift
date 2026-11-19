# keymapper

`keymapper` is a Python library and CLI scaffold for keyboard input remapping on
Linux. The initial release establishes the package structure; keyboard device
discovery and remapping are not implemented yet.

## Requirements

- Linux with Python 3.10 or newer
- Access to keyboard input devices for future hardware features

Device permissions, desktop environments, and keyboard capabilities vary.
Compatibility with every keyboard or desktop environment is not guaranteed.
Future input handling must provide an emergency reset and avoid leaving
physical input devices grabbed.

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
keymapper --version
keymapper --help
keymapper list-devices
```

`list-devices` is currently a placeholder and reports that device discovery is
not implemented.

## Package layout

- `src/keymapper/device_manager.py`: keyboard device discovery and selection
- `src/keymapper/listener.py`: input event reading
- `src/keymapper/mapping_engine.py`: key remapping
- `src/keymapper/shortcut_manager.py`: shortcut mapping
- `src/keymapper/macro_engine.py`: macro execution
- `src/keymapper/virtual_keyboard.py`: virtual keyboard output
- `src/keymapper/config_manager.py`: configuration and profiles
- `src/keymapper/cli.py`: Typer command-line interface
- `configs/default.yaml`: starter configuration
