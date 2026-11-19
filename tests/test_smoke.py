"""Smoke tests for package importability."""


def test_package_imports() -> None:
    """The package exposes its version after installation."""
    import keyshift

    assert keyshift.__version__ == "0.1.0"
