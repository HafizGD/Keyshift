"""Verify shipped examples follow the supported configuration schema."""

from pathlib import Path

from keyshift.config_manager import load_config


def test_workstation_example_is_valid() -> None:
    example_path = Path(__file__).parents[1] / "examples" / "workstation.yaml"

    config = load_config(example_path)

    assert config["remaps"] == {"CapsLock": "LeftCtrl"}
    assert config["temporary_mappings"][0]["mode"] == "layer"
