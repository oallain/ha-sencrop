"""The integration must load on the oldest supported Home Assistant."""

import ast
from pathlib import Path

import pytest

SOURCES = sorted((Path(__file__).parent.parent / "custom_components").rglob("*.py"))

# HA 2025.4 (minimum in hacs.json) runs on Python 3.13.
MIN_PYTHON = (3, 13)


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_sources_parse_on_minimum_python(path: Path) -> None:
    ast.parse(path.read_text(), filename=str(path), feature_version=MIN_PYTHON)
