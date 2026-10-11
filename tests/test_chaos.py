from pathlib import Path

import pytest

from smogon_dataset.parsers.chaos import ChaosTables, canonical_raw, parse_chaos, read_json, rebuild_chaos

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("**/chaos/*.json"))


def _parse(path: Path) -> ChaosTables:
    month = path.parts[path.parts.index("fixtures") + 1]
    format, cutoff = path.stem.rsplit("-", 1)
    return parse_chaos(read_json(path), month, format, int(cutoff))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: str(p).split("fixtures/")[1])
def test_parse_chaos_is_lossless(path: Path) -> None:
    assert rebuild_chaos(_parse(path)) == canonical_raw(read_json(path))


def test_old_files_have_no_usage_nor_viability() -> None:
    tables = _parse(Path(__file__).parent / "fixtures/2014-11/chaos/stabmons-0.json")
    assert tables.pokemon["usage"].null_count() == tables.pokemon.height
    assert "Viability Ceiling" not in tables.info["sections"][0]


def test_checks_have_the_same_shape_in_every_era() -> None:
    old = _parse(Path(__file__).parent / "fixtures/2020-11-H1/chaos/gen8nfe-0.json").checks
    new = _parse(Path(__file__).parent / "fixtures/2026-09/chaos/gen9nfe-0.json").checks
    assert old.schema == new.schema
    assert old.filter(pokemon="Mr. Mime-Galar", opponent="Thwackey").select("n", "p", "d").row(0) == (
        24.0,
        0.625,
        0.0988211769,
    )


def test_tera_types_absent_vs_recorded() -> None:
    before = _parse(Path(__file__).parent / "fixtures/2023-07/chaos/gen9nfe-0.json")
    after = _parse(Path(__file__).parent / "fixtures/2026-09/chaos/gen9nfe-0.json")
    assert "Tera Types" not in before.info["sections"][0]
    assert "Tera Types" in after.info["sections"][0]
    assert after.weights.filter(section="tera_types").height > 0


def test_unknown_key_fails_loudly() -> None:
    raw = {
        "info": {"metagame": "gen9ou", "cutoff": 0, "cutoff deviation": 0, "number of battles": 1},
        "data": {"Pikachu": {"Raw count": 1, "Shiny": {"yes": 1}}},
    }
    with pytest.raises(ValueError, match="Shiny"):
        parse_chaos(raw, "2026-09", "gen9ou", 0)


def test_null_usage_survives_the_round_trip() -> None:
    # gen9monocolor 2026-09 at 1630: a single battle, every weight is 0 and usage is null.
    raw = {
        "info": {"metagame": "gen9monocolor", "cutoff": 1630, "cutoff deviation": 0, "number of battles": 1},
        "data": {"Mienshao": {"Raw count": 1, "Abilities": {"reckless": 0}, "Checks and Counters": {}, "usage": None}},
    }
    assert rebuild_chaos(parse_chaos(raw, "2026-09", "gen9monocolor", 1630)) == canonical_raw(raw)
