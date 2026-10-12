from pathlib import Path

import polars as pl

from smogon_dataset.formats import build_formats, read_battles


def _inventory(formats: dict[str, dict[str, list[int]]]) -> pl.DataFrame:
    rows = [
        {"month": month, "section": "", "format": name, "cutoff": cutoff}
        for month, names in formats.items()
        for name, cutoffs in names.items()
        for cutoff in cutoffs
    ]
    return pl.DataFrame(
        rows, schema={"month": pl.String, "section": pl.String, "format": pl.String, "cutoff": pl.Int32}
    )


LOW = [0, 1500, 1630, 1760]
HIGH = [0, 1500, 1695, 1825]

INVENTORY = _inventory(
    {
        "2015-01": {"ou": HIGH, "ubers": LOW, "smogondoubles": HIGH, "gen5ou": LOW, "vgc2015": LOW, "lc": LOW},
        # Gen 7 has just come out: both OU get the high cutoff, but only gen 7 is current.
        "2016-11": {"ou": HIGH, "ubers": LOW, "gen7ou": HIGH, "gen7ubers": LOW, "gen71v1": LOW},
        "2026-09": {
            "gen9ou": HIGH,
            "gen6ou": LOW,
            "gen9monotype": LOW,
            "gen9monotype-monobug": LOW,
            "gen9vgc2026regi": LOW,
            "gen9vgc2026regibo3": LOW,
        },
    }
)
BATTLES = pl.DataFrame(
    {
        "month": ["2015-01", "2026-09", "2026-09"],
        "format": ["vgc2015", "gen9vgc2026regi", "gen9vgc2026regibo3"],
        "battles": [1000, 500, 9000],
    }
)


def _formats() -> dict[tuple[str, str], dict[str, object]]:
    table = build_formats(INVENTORY, BATTLES)
    return {(row["month"], row["format"]): row for row in table.iter_rows(named=True)}


def test_unprefixed_names_are_gen6() -> None:
    ou = _formats()["2015-01", "ou"]
    assert (ou["format_id"], ou["gen"], ou["family"]) == ("gen6ou", 6, "ou")


def test_generation_is_one_digit() -> None:
    row = _formats()["2016-11", "gen71v1"]
    assert (row["gen"], row["family"]) == (7, "1v1")


def test_standard_cutoff_and_battles() -> None:
    formats = _formats()
    assert formats["2015-01", "ou"]["standard_cutoff"] == 1695
    assert formats["2015-01", "gen5ou"]["standard_cutoff"] == 1630
    assert formats["2015-01", "vgc2015"]["battles"] == 1000
    assert formats["2015-01", "ou"]["battles"] is None


def test_every_ou_is_its_own_lite_series() -> None:
    formats = _formats()
    assert formats["2015-01", "ou"]["lite_series"] == "gen6ou"
    assert formats["2026-09", "gen6ou"]["lite_series"] == "gen6ou"
    assert formats["2015-01", "gen5ou"]["lite_series"] == "gen5ou"


def test_tier_series_follows_the_current_generation() -> None:
    formats = _formats()
    assert formats["2015-01", "ubers"]["lite_series"] == "ubers"
    assert formats["2015-01", "smogondoubles"]["lite_series"] == "doublesou"
    assert formats["2016-11", "gen7ubers"]["lite_series"] == "ubers"
    assert formats["2016-11", "ubers"]["lite_series"] is None


def test_formats_left_out_of_lite() -> None:
    formats = _formats()
    assert formats["2015-01", "lc"]["lite_series"] is None
    assert formats["2026-09", "gen9monotype"]["lite_series"] == "monotype"
    assert formats["2026-09", "gen9monotype-monobug"]["lite_series"] is None


def test_vgc_series_is_the_most_played_vgc_format() -> None:
    formats = _formats()
    assert formats["2015-01", "vgc2015"]["lite_series"] == "vgc"
    assert formats["2026-09", "gen9vgc2026regibo3"]["lite_series"] == "vgc"
    assert formats["2026-09", "gen9vgc2026regi"]["lite_series"] is None


def test_read_battles_skips_the_month_being_synced(tmp_path: Path) -> None:
    usage = pl.DataFrame({"month": ["2026-08"], "format": ["gen9ou"], "battles": [7]})
    (tmp_path / "2026-08").mkdir()
    usage.write_parquet(tmp_path / "2026-08/usage.parquet")
    (tmp_path / "2026-09.part").mkdir()
    (tmp_path / "2026-09.part/usage.parquet").write_bytes(b"PAR1 half written")

    assert read_battles(tmp_path).rows() == [("2026-08", "gen9ou", 7)]
