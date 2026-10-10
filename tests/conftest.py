from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Real Smogon files from each era, laid out like the server: fixtures/<month>/<section>/<file>."""
    return FIXTURES_DIR
