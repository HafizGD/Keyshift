"""Record and execute keyboard macros."""

from collections.abc import Sequence


def play_macro(events: Sequence[object]) -> None:
    """Play a sequence of keyboard events."""
    raise NotImplementedError("Macro playback is not implemented yet.")
