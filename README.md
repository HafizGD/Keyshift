# keyshift

`keyshift` is a Python library and CLI for remapping Linux keyboard input
through a virtual keyboard. It uses evdev input event devices and `/dev/uinput`;
it does not modify keyboard firmware.

Compatibility depends on kernel device capabilities, permissions, desktop
environment, and keyboard layout. A physical keyboard may expose multiple
event nodes, while Bluetooth keyboards, KVM switches, remote desktops, or
unusual devices may not be discoverable or behave as expected.

## Safety and permissions

Reading `/dev/input/event*` can expose every keystroke, including passwords.
Members of the `input` group should run only trusted software. Keyboard input
nodes are commonly owned by that group; group changes take effect after
logging out and back in.

`keyshift run` exclusively grabs its selected input device. It requires a
finite `--timeout`, creates the virtual output before grabbing input, and
releases held virtual keys and the grab on shutdown. The default emergency
chord is `LeftCtrl+LeftAlt+LeftShift+Esc`, held together for one second. A
custom chord can be set in the configuration. Keep a backup keyboard or
another way to stop the process available, and do not test remapping on a
critical system before reviewing the configuration.

To prepare `/dev/uinput` access, load the kernel module and install a udev rule
that grants the `input` group access with mode `0660`. For example:

```shell
sudo modprobe uinput
sudo tee /etc/udev/rules.d/99-keyshift.rules >/dev/null <<'EOF'
KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Add your account to `input` only if you understand the keystroke-access risk.
Do not grant permanent root privileges to keyshift.

## Development setup

```shell
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

Release artifacts can be checked locally with `python -m build` and
`python -m twine check dist/*`. GitHub Actions runs the test suite and these
package checks on Python 3.10 through 3.13.

## CLI

```shell
keyshift --version
keyshift --help
keyshift list-devices
keyshift list-devices --json
keyshift monitor --device 1 --timeout 15
keyshift remap CapsLock Ctrl
keyshift remap A B --for 10m
keyshift remap A B --toggle F1
keyshift remap A B --while-held CapsLock
keyshift unmap A
keyshift profile --create gaming
keyshift profile gaming
keyshift select-device 1
keyshift status
keyshift doctor
keyshift run --device 1 --timeout 60
keyshift run --device 1 --timeout 60 --reconnect
keyshift reset --force
```

`list-devices` filters event nodes by keyboard key capabilities. `monitor`
prints press, release, and repeat events without grabbing the device. `run`
applies configured mappings, shortcuts, and macros; it grabs the selected
input device and uses `/dev/uinput` for output. Only one service instance can
run at a time. `--reconnect` waits for the selected physical keyboard to
reappear, up to the run timeout.

Remaps are stored in the active profile or global configuration. Temporary
remaps support a fixed duration (`--for`, using `s`, `m`, or `h`, capped at 24
hours), a toggle key (`--toggle`), or a held layer key (`--while-held`). A
temporary remap overrides a permanent remap for the same source key.

The emergency chord is configurable in `config.yaml`, for example:

```yaml
emergency_exit: LeftCtrl+LeftAlt+LeftShift+Esc
temporary_mappings:
  - mode: layer
    source: A
    target: B
    trigger: CapsLock
```

Shortcut triggers and outputs use Linux key codes rather than translated
characters, so behavior depends on the active layout. Macro text entry uses a
basic US key layout, not a character-layout translation service.

`doctor` performs read-only checks for dependencies, readable keyboard nodes,
configuration validity, `/dev/uinput`, the uinput module, and a running service.
Missing devices or uinput access are warnings; invalid configuration or missing
required dependencies make it exit nonzero.

The service writes rotating logs to
`~/.local/state/keyshift/keyshift.log` (or `$XDG_STATE_HOME/keyshift/`), with
owner-only file permissions. `--debug` increases diagnostic detail but does not
log key names, codes, or key-event values.

## Troubleshooting checklist

- Run `keyshift doctor` before starting the service; fix any dependency or
  configuration failures it reports.
- If input devices are unreadable, confirm group membership with `groups`,
  add the account to `input` if appropriate, then log out and back in. The
  `input` group can expose all keystrokes to processes run by that account.
- If `/dev/uinput` is missing, load the module with `sudo modprobe uinput`.
  If it exists but is inaccessible, check the udev group/mode rule and refresh
  the login session after group changes.
- Use `keyshift list-devices` and `keyshift select-device` to choose a keyboard
  node that actually exposes normal key capabilities. A physical keyboard can
  have several event nodes, and not every environment exposes one that
  keyshift can use.
- Before `keyshift run`, verify the emergency chord in the configuration and
  use a short finite timeout. Hold the full chord for one second to stop, or
  use `Ctrl+C`; keep an alternate input route available during testing.
- Review the private service log for lifecycle and device-disconnect messages.
  Logs intentionally omit individual key events.

## Configuration and profiles

YAML configuration is stored under `~/.config/keyshift/` (or
`$XDG_CONFIG_HOME/keyshift/`): `config.yaml`, `state.yaml`, and
`profiles/<name>.yaml`. Writes are atomic. Invalid files are preserved as
`.bak` files, reset to defaults, and reported with a recovery warning.
See [`examples/workstation.yaml`](./examples/workstation.yaml) for a validated
configuration example.

## Package layout

- `src/keyshift/device_manager.py`: keyboard device discovery and selection
- `src/keyshift/listener.py`: input event reading
- `src/keyshift/mapping_engine.py`: key remapping and temporary mapping modes
- `src/keyshift/shortcut_manager.py`: shortcut mapping
- `src/keyshift/macro_engine.py`: macro execution
- `src/keyshift/virtual_keyboard.py`: virtual keyboard output
- `src/keyshift/config_manager.py`: configuration and profiles
- `src/keyshift/service.py`: safe service lifecycle and event pipeline
- `src/keyshift/diagnostics.py`: read-only system and configuration checks
- `src/keyshift/logging_config.py`: private rotating service logs
- `src/keyshift/cli.py`: Typer command-line interface
- `configs/default.yaml`: starter configuration
