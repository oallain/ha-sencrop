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
    assert manifest["version"] == "0.1.1"
    assert manifest["codeowners"] == ["@oallain"]
    assert manifest["requirements"] == []


def test_brand_icons() -> None:
    from PIL import Image

    brand = ROOT / "custom_components/sencrop/brand"
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        with Image.open(brand / name) as image:
            assert image.format == "PNG"
            assert image.size == (size, size)
