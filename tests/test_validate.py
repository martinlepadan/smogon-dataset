import json
from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.pokedex import build_pokemon
from smogon_dataset.validate import ValidationError, check_formats, check_pokemon, check_table

FIXTURES = Path(__file__).parent / "fixtures"
POKEMON_IDS = pl.Series(["greattusk", "rotomwash"])
FORMATS = pl.Series(["gen9ou"])
KEY = {"month": "2026-09", "format": "gen9ou", "cutoff": 1695}


def _usage(**changes: object) -> pl.DataFrame:
    row = KEY | {"pokemon_id": "greattusk", "rank": 1, "usage_pct": 33.1, "raw": 10, "raw_pct": 27.9, "real": 8}
    row |= {"real_pct": 27.7} | changes
    return pl.DataFrame([row], schema_overrides={"cutoff": pl.Int32, "rank": pl.Int32, "usage_pct": pl.Float64})


def _teammates(**changes: object) -> pl.DataFrame:
    row = KEY | {"pokemon_id": "greattusk", "teammate_id": "rotomwash", "association_score": None, "count": 3.5}
    schema = {"cutoff": pl.Int32, "teammate_id": pl.String, "association_score": pl.Float32, "count": pl.Float32}
    return pl.DataFrame([row | changes], schema_overrides=schema)


def _check(name: str, table: pl.DataFrame) -> None:
    check_table(name, table, POKEMON_IDS, FORMATS)


def test_a_sound_table_passes() -> None:
    _check("usage", _usage())
    _check("usage", _usage(usage_pct=None))
    _check("teammates", _teammates())
    _check("teammates", _teammates(teammate_id=None))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"rank": 0}, "rank fails greater_than_or_equal_to"),
        ({"usage_pct": -1.0}, "usage_pct fails greater_than_or_equal_to"),
        ({"cutoff": 1700}, "cutoff fails isin"),
        ({"month": "2026-9"}, "month fails str_matches"),
        ({"pokemon_id": "fakemon"}, "pokemon_id missing from the pokemon table: ['fakemon']"),
        ({"format": "gen9fake"}, "formats missing from the formats table: ['gen9fake']"),
    ],
)
def test_a_broken_rule_is_named_with_its_month_and_table(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError) as error:
        _check("usage", _usage(**changes))
    assert message in str(error.value)
    assert str(error.value).startswith(f"{changes.get('month', '2026-09')}/usage: ")


def test_types_and_columns_are_part_of_the_contract() -> None:
    with pytest.raises(ValidationError, match="rank fails dtype"):
        _check("usage", _usage().with_columns(pl.col("rank").cast(pl.Int64)))
    with pytest.raises(ValidationError, match="column_in_schema"):
        _check("usage", _usage().with_columns(extra=1))


def test_one_row_per_pokemon_and_file() -> None:
    with pytest.raises(ValidationError, match="uniqueness"):
        _check("usage", pl.concat([_usage(), _usage(rank=2)]))


def test_usage_of_a_file_cannot_exceed_six_pokemon_per_team() -> None:
    full_team = pl.concat([_usage(usage_pct=300.0), _usage(pokemon_id="rotomwash", usage_pct=300.0002)])
    _check("usage", full_team)
    with pytest.raises(ValidationError, match="adds up to more than 600%"):
        _check("usage", pl.concat([_usage(usage_pct=400.0), _usage(pokemon_id="rotomwash", usage_pct=300.0)]))


def test_teammates_carry_a_score_or_a_count_never_both() -> None:
    with pytest.raises(ValidationError, match="1 rows without exactly one of"):
        _check("teammates", _teammates(association_score=1.0))
    with pytest.raises(ValidationError, match="1 rows without exactly one of"):
        _check("teammates", _teammates(count=None))
    with pytest.raises(ValidationError, match="teammate_id missing from the pokemon table"):
        _check("teammates", _teammates(teammate_id="fakemon"))


def test_pokemon_table() -> None:
    pokemon = build_pokemon(json.loads((FIXTURES / "showdown/pokedex.json").read_text()))
    check_pokemon(pokemon)
    with pytest.raises(ValidationError, match="type1 fails isin"):
        check_pokemon(pokemon.with_columns(type1=pl.lit("Sound")))


def test_formats_table() -> None:
    row = {"month": "2026-09", "format": "gen9ou", "format_id": "gen9ou", "gen": 9, "family": "ou", "battles": 5}
    row |= {"standard_cutoff": 1695, "is_special_month": False, "lite_series": "gen9ou"}
    formats = pl.DataFrame([row]).with_columns(pl.col("gen", "standard_cutoff").cast(pl.Int32))
    check_formats(formats)
    twin = formats.with_columns(format=pl.lit("ou"))
    with pytest.raises(ValidationError, match="two formats in one Lite series"):
        check_formats(pl.concat([formats, twin]))
