import pytest

from smogon_dataset.config import standard_cutoff


@pytest.mark.parametrize(
    ("format_id", "expected"),
    [
        ("gen9ou", 1695),
        ("gen1ou", 1695),
        ("gen9doublesou", 1695),
        ("gen9uu", 1630),
        ("gen9ubers", 1630),
    ],
)
def test_standard_cutoff(format_id: str, expected: int) -> None:
    assert standard_cutoff(format_id) == expected
