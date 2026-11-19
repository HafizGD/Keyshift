"""Smoke tests for package importability."""


def test_package_imports() -> None:
    """The package exposes its version after installation."""
    import keymapper

    assert keymapper.__version__ == "0.1.0"
