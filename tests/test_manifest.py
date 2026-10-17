"""Static checks on the integration manifest."""

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_manifest_is_valid() -> None:
    manifest = json.loads(
        (ROOT / "custom_components/sencrop/manifest.json").read_text()
    )
    assert manifest["domain"] == "sencrop"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["version"] == "0.1.0"
    assert manifest["codeowners"] == ["@oallain"]
    assert manifest["requirements"] == []
