"""Load and save keyshift configuration and profiles."""

from pathlib import Path


def load_config(path: Path) -> dict[str, object]:
    """Load configuration from a file."""
    raise NotImplementedError("Configuration loading is not implemented yet.")


def save_config(path: Path, config: dict[str, object]) -> None:
    """Save configuration to a file."""
    raise NotImplementedError("Configuration saving is not implemented yet.")
