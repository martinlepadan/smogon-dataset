from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Samples of Smogon files, organized by era (2014, 2017, 2020, 2023, 2026)."""
    return FIXTURES_DIR
