from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def hello_world_payload() -> dict:
    return json.loads((FIXTURES / "repo_octocat_hello_world.json").read_text(encoding="utf-8"))
