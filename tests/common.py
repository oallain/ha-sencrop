"""Helpers shared by the Sencrop tests."""

import base64
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load `tests/fixtures/<name>.json`."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def make_jwt(exp: int, iat: int | None = None) -> str:
    """Build an unsigned JWT carrying the given expiry."""

    def encode(part: dict) -> str:
        raw = json.dumps(part).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    claims = {"exp": exp, "iat": iat if iat is not None else exp - 86400}
    return f"{encode({'alg': 'ES256', 'typ': 'JWT'})}.{encode(claims)}.signature"
