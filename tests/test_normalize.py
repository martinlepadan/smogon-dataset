import json
from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.normalize import UnknownPokemonError, month_tables, normalize_month
from smogon_dataset.parsers.chaos import CHECKS_SCHEMA, POKEMON_SCHEMA, WEIGHTS_SCHEMA
from smogon_dataset.pokedex import build_pokemon

FIXTURES = Path(__file__).parent / "fixtures"
KEY = {"format": "gen9ou", "cutoff": 1695}


def _canonical_month(folder: Path, usage_names: tuple[str, ...] = ("Great Tusk", "Rotom-Wash")) -> Path:
    """A tiny month of canonical tables, as sync would leave it."""
    key = {"month": folder.name} | KEY
    tusk = key | {"pokemon": "Great Tusk"}
    weights = [
        tusk | {"section": "abilities", "key": "protosynthesis", "weight": 10.0},
        tusk | {"section": "moves", "key": "earthquake", "weight": 9.0},
        tusk | {"section": "spreads", "key": "Jolly:0/252/4/0/0/252", "weight": 7.0},
        tusk | {"section": "happiness", "key": "255", "weight": 10.0},
        tusk | {"section": "teammates", "key": "Rotom-Wash", "weight": 3.5},
        tusk | {"section": "teammates", "key": "empty", "weight": 0.5},
    ]
    usage = [
        key
        | {"rank": rank, "pokemon": name, "usage_pct": 50.0, "raw": 10, "raw_pct": 50.0, "real": 8, "real_pct": 50.0}
        for rank, name in enumerate(usage_names, start=1)
    ]
    leads = [key | {"rank": 1, "pokemon": "Great Tusk", "usage_pct": 60.0, "raw": 6, "raw_pct": 60.0}]
    tables = {
        "chaos_weights": pl.DataFrame(weights, schema=WEIGHTS_SCHEMA),
        "chaos_pokemon": pl.DataFrame(
            [tusk | {"raw_count": 10, "usage": 0.5, "viability_ceiling": [120, 90, 81, 63]}], schema=POKEMON_SCHEMA
        ),
        "chaos_checks": pl.DataFrame(
            [tusk | {"opponent": "Rotom-Wash", "n": 40.0, "p": 0.6, "d": 0.05}], schema=CHECKS_SCHEMA
        ),
        "usage": pl.DataFrame(usage).with_columns(battles=pl.lit(5), avg_weight=pl.lit(0.25)),
        "leads": pl.DataFrame(leads).with_columns(total_leads=pl.lit(10)),
        "metagame": pl.DataFrame([key | {"style": "offense", "pct": 40.0}]),
        "metagame_stalliness": pl.DataFrame(
            [key | {"bin": -1.0, "hashes": 3, "mean": 0.2, "pct_per_hash": 0.5}],
        ),
    }
    folder.mkdir(parents=True)
    for name, table in tables.items():
        table.write_parquet(folder / f"{name}.parquet")
    return folder


def _row(table: pl.LazyFrame) -> dict[str, object]:
    return table.collect().row(0, named=True)


def test_weights_are_split_into_one_table_per_section(tmp_path: Path) -> None:
    tables = month_tables(_canonical_month(tmp_path / "2026-09"))
    assert _row(tables["abilities"]) == {"month": "2026-09"} | KEY | {
        "pokemon_id": "greattusk",
        "ability": "protosynthesis",
        "weight": 10.0,
    }
    assert _row(tables["moves"])["move"] == "earthquake"
    assert _row(tables["happiness"])["happiness"] == 255
    assert tables["items"].collect().is_empty()


def test_spreads_are_split_into_nature_and_evs(tmp_path: Path) -> None:
    spread = _row(month_tables(_canonical_month(tmp_path / "2026-09"))["spreads"])
    assert spread["nature"] == "Jolly"
    assert [spread[ev] for ev in ("hp_ev", "atk_ev", "def_ev", "spa_ev", "spd_ev", "spe_ev")] == [0, 252, 4, 0, 0, 252]
    assert spread["weight"] == 7.0


@pytest.mark.parametrize(
    ("month", "filled", "null"),
    [
        ("2021-03", "association_score", "count"),
        ("2020-11-H1", "association_score", "count"),
        ("2021-04", "count", "association_score"),
    ],
)
def test_teammates_meaning_depends_on_the_month(tmp_path: Path, month: str, filled: str, null: str) -> None:
    teammates = month_tables(_canonical_month(tmp_path / month))["teammates"].collect()
    assert teammates["teammate_id"].to_list() == ["rotomwash", None]
    assert teammates[filled].to_list() == [3.5, 0.5]
    assert teammates[null].null_count() == 2


def test_file_level_numbers_go_to_cutoffs(tmp_path: Path) -> None:
    tables = month_tables(_canonical_month(tmp_path / "2026-09"))
    assert _row(tables["cutoffs"]) == {"month": "2026-09"} | KEY | {
        "battles": 5,
        "avg_weight_per_team": 0.25,
        "total_leads": 10,
        "stalliness_mean": 0.2,
        "pct_per_hash": 0.5,
    }
    assert "battles" not in tables["usage"].collect_schema()
    assert _row(tables["stalliness"]) == {"month": "2026-09"} | KEY | {"bin": -1.0, "hashes": 3}


def test_movesets_and_checks(tmp_path: Path) -> None:
    tables = month_tables(_canonical_month(tmp_path / "2026-09"))
    moveset = _row(tables["movesets"])
    assert (moveset["players"], moveset["gxe_top"], moveset["gxe_p99"], moveset["gxe_p95"]) == (120, 90, 81, 63)
    check = _row(tables["checks_counters"])
    assert (check["pokemon_id"], check["opponent_id"]) == ("greattusk", "rotomwash")


def test_normalize_month_writes_a_folder_or_names_the_unknown_pokemon(tmp_path: Path) -> None:
    pokemon = build_pokemon(json.loads((FIXTURES / "showdown/pokedex.json").read_text()))
    interim, complete = tmp_path / "interim", tmp_path / "complete"

    normalize_month(_canonical_month(interim / "2026-09"), pokemon, complete)
    assert pl.read_parquet(complete / "2026-09/usage.parquet")["pokemon_id"].to_list() == ["greattusk", "rotomwash"]
    assert not (complete / "2026-09.part").exists()

    with pytest.raises(UnknownPokemonError, match="Fakemon"):
        normalize_month(_canonical_month(interim / "2026-08", ("Great Tusk", "Fakemon")), pokemon, complete)
    assert not (complete / "2026-08").exists()


def test_matchup_tables_use_the_format_name(tmp_path: Path) -> None:
    folder = _canonical_month(tmp_path / "2026-09")
    key = {"month": "2026-09", "format": "gen9monotype-matchup_chart", "cutoff": 0}
    pl.DataFrame([key | {"type": "Bug", "opponent": "Fire", "battles": 12.0, "win_pct": 30.0}]).write_parquet(
        folder / "monotype_matchups.parquet"
    )
    pl.DataFrame([key | {"type": "Bug", "viability_score": 1.5}]).write_parquet(
        folder / "monotype_type_ranking.parquet"
    )

    tables = month_tables(folder)
    assert _row(tables["monotype_matchups"])["format"] == "gen9monotype"
    assert _row(tables["monotype_type_ranking"])["format"] == "gen9monotype"
