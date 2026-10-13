from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.lite import TABLES, WEIGHT_TABLES, MissingFromLiteError, build_lite

POKEMON = pl.DataFrame({"pokemon_id": ["greattusk"], "name": ["Great Tusk"]})


def _formats(rows: list[tuple[str, str, int, str | None]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=["month", "format", "standard_cutoff", "lite_series"], orient="row").with_columns(
        is_special_month=pl.col("month").str.len_chars() > len("2020-11")
    )


def _complete_month(complete: Path, month: str, files: list[tuple[str, int]], weight: float = 2.5) -> None:
    """A month of Complete where every table holds one row per (format, cutoff) of `files`."""
    (complete / month).mkdir(parents=True)
    rows = pl.DataFrame(files, schema=["format", "cutoff"], orient="row").select(pl.lit(month).alias("month"), pl.all())
    for name in TABLES:
        table = rows.with_columns(pokemon_id=pl.lit("greattusk"))
        if name in WEIGHT_TABLES:
            table = table.with_columns(weight=pl.lit(weight))
        table.write_parquet(complete / month / f"{name}.parquet")


def test_lite_keeps_the_series_at_their_standard_cutoff(tmp_path: Path) -> None:
    complete = tmp_path / "complete"
    _complete_month(complete, "2020-11", [("gen8ou", 1695), ("gen8ou", 1825), ("gen8lc", 1630)])
    _complete_month(complete, "2020-12", [("gen8ou", 1695), ("gen8ubers", 1630), ("gen8ubers", 0)])
    formats = _formats(
        [
            ("2020-11", "gen8ou", 1695, "gen8ou"),
            ("2020-11", "gen8lc", 1630, None),
            ("2020-12", "gen8ou", 1695, "gen8ou"),
            ("2020-12", "gen8ubers", 1630, "ubers"),
        ]
    )

    build_lite(complete, POKEMON, formats, tmp_path / "lite")

    kept = [("2020-11", "gen8ou", 1695), ("2020-12", "gen8ou", 1695), ("2020-12", "gen8ubers", 1630)]
    for name in TABLES:
        assert pl.read_parquet(tmp_path / f"lite/{name}.parquet").select("month", "format", "cutoff").rows() == kept
    assert pl.read_csv(tmp_path / "lite/usage.csv").select("month", "format", "cutoff").rows() == kept
    assert pl.read_parquet(tmp_path / "lite/formats.parquet")["format"].to_list() == ["gen8ou", "gen8ou", "gen8ubers"]
    assert pl.read_csv(tmp_path / "lite/pokemon.csv").rows() == [("greattusk", "Great Tusk")]


def test_lite_leaves_out_special_months_and_months_not_normalized(tmp_path: Path) -> None:
    complete = tmp_path / "complete"
    _complete_month(complete, "2020-11", [("gen8ou", 1695)])
    _complete_month(complete, "2020-11-H1", [("gen8ou", 1695)])
    (complete / "2020-12.part").mkdir()
    (tmp_path / "lite").mkdir()
    (tmp_path / "lite/.gitkeep").touch()
    formats = _formats([(month, "gen8ou", 1695, "gen8ou") for month in ("2020-11", "2020-11-H1", "2020-12", "2021-01")])

    build_lite(complete, POKEMON, formats, tmp_path / "lite")

    assert pl.read_parquet(tmp_path / "lite/usage.parquet")["month"].to_list() == ["2020-11"]
    assert pl.read_parquet(tmp_path / "lite/formats.parquet")["month"].to_list() == ["2020-11"]
    assert (tmp_path / "lite/.gitkeep").exists()
    assert not (tmp_path / "lite.part").exists()


def test_weights_become_the_share_of_the_sets_of_the_pokemon(tmp_path: Path) -> None:
    complete = tmp_path / "complete"
    _complete_month(complete, "2020-11", [("gen8ou", 1695)])
    key = {"month": "2020-11", "format": "gen8ou", "cutoff": 1695, "pokemon_id": "greattusk"}
    abilities = [key | {"ability": "protosynthesis", "weight": 150.0}, key | {"ability": "none", "weight": 50.0}]
    moves = [
        key | {"move": "earthquake", "weight": 190.0},
        key | {"move": "rapidspin", "weight": 2.0 / 3},
        key | {"move": "tackle", "weight": 0.19},
        key | {"move": "splash", "weight": 0.0},
        key | {"pokemon_id": "unseen", "move": "tackle", "weight": 0.0},
    ]
    pl.DataFrame(abilities).write_parquet(complete / "2020-11/abilities.parquet")
    pl.DataFrame(moves).write_parquet(complete / "2020-11/moves.parquet")

    build_lite(complete, POKEMON, _formats([("2020-11", "gen8ou", 1695, "gen8ou")]), tmp_path / "lite")

    assert pl.read_parquet(tmp_path / "lite/abilities.parquet").select("ability", "pct").rows() == [
        ("protosynthesis", 75.0),
        ("none", 25.0),
    ]
    # tackle is at 0.095 %, under the 0.1 % line.
    lite_moves = pl.read_parquet(tmp_path / "lite/moves.parquet")
    assert lite_moves.select("move", "pct").rows() == [("earthquake", 95.0), ("rapidspin", 0.333)]
    assert "weight" not in lite_moves.columns


def test_lite_fails_when_a_series_has_no_usage(tmp_path: Path) -> None:
    complete = tmp_path / "complete"
    _complete_month(complete, "2020-11", [("gen8ou", 1630)])
    (tmp_path / "lite").mkdir()

    with pytest.raises(MissingFromLiteError, match="gen8ou"):
        build_lite(complete, POKEMON, _formats([("2020-11", "gen8ou", 1695, "gen8ou")]), tmp_path / "lite")

    assert list((tmp_path / "lite").iterdir()) == []


def test_lite_takes_the_months_it_cannot_derive_from_a_published_lite(tmp_path: Path) -> None:
    complete = tmp_path / "complete"
    _complete_month(complete, "2020-11", [("gen8ou", 1695)])
    _complete_month(complete, "2020-12", [("gen8ou", 1695), ("gen8ubers", 1630)])
    formats = _formats(
        [
            ("2020-11", "gen8ou", 1695, "gen8ou"),
            ("2020-12", "gen8ou", 1695, "gen8ou"),
            ("2020-12", "gen8ubers", 1630, "ubers"),
        ]
    )
    build_lite(complete, POKEMON, formats, tmp_path / "published")

    # Only 2020-12 is at hand, this time without its ubers, and 2021-01 is new.
    later = tmp_path / "later"
    _complete_month(later, "2020-12", [("gen8ou", 1695)])
    _complete_month(later, "2021-01", [("gen8ou", 1695), ("gen8lc", 1630)])
    later_formats = _formats(
        [
            ("2020-12", "gen8ou", 1695, "gen8ou"),
            ("2021-01", "gen8ou", 1695, "gen8ou"),
            ("2021-01", "gen8lc", 1630, None),
        ]
    )

    build_lite(later, POKEMON, later_formats, tmp_path / "lite", tmp_path / "published")

    kept = [("2020-11", "gen8ou"), ("2020-12", "gen8ou"), ("2021-01", "gen8ou")]
    for name in TABLES:
        table = pl.read_parquet(tmp_path / f"lite/{name}.parquet")
        assert table.select("month", "format").rows() == kept
        published = pl.read_parquet(tmp_path / f"published/{name}.parquet")
        assert table.filter(month="2020-11").equals(published.filter(month="2020-11"))
    assert pl.read_parquet(tmp_path / "lite/formats.parquet").select("month", "format").rows() == kept
    assert pl.read_csv(tmp_path / "lite/moves.csv").select("month", "format").rows() == kept
