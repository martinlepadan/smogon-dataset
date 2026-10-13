from pathlib import Path

import polars as pl
import pytest

import smogon_stats as ss
from smogon_stats import reader

MONTHS = ["2014-11", "2014-12", "2015-01", "2015-02", "2016-01", "2016-02-H1"]


@pytest.fixture
def downloads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Fake Kaggle under tmp_path, one folder per dataset; returns the log of downloaded files."""
    for year in (2014, 2015, 2016):
        year_dir = tmp_path / f"smogon-usage-stats-complete-{year}"
        year_months = [month for month in MONTHS if month.startswith(str(year))]
        files = [("usage", month) for month in year_months]
        if year == 2014:
            files += [("mega", month) for month in year_months]
        for table, month in files:
            (year_dir / table).mkdir(parents=True, exist_ok=True)
            pl.DataFrame(
                {
                    "month": [month] * 3,
                    "format": ["ou", "ou", "uu"],
                    "cutoff": [0, 1500, 0],
                    "pokemon_id": ["pikachu"] * 3,
                }
            ).write_parquet(year_dir / table / f"{month}.parquet")
        pl.DataFrame(files, schema=["table", "month"], orient="row").write_parquet(year_dir / "files.parquet")
        pl.DataFrame({"month": year_months, "format": ["ou"] * len(year_months)}).write_parquet(
            year_dir / "formats.parquet"
        )
        pl.DataFrame({"pokemon_id": ["pikachu"], "pokedex_of": [year]}).write_parquet(year_dir / "pokemon.parquet")

    lite_dir = tmp_path / "smogon-usage-stats-lite"
    lite_dir.mkdir()
    pl.DataFrame({"month": ["2014-11", "2014-11"], "format": ["ou", "uu"]}).write_parquet(lite_dir / "usage.parquet")

    log: list[tuple[str, str]] = []

    def fake_download(dataset: str, file: str) -> Path:
        log.append((dataset.removeprefix("martinlepadan/smogon-usage-stats-"), file))
        return tmp_path / dataset.removeprefix("martinlepadan/") / file

    monkeypatch.setattr(reader, "download", fake_download)
    monkeypatch.setattr(reader, "_latest_year", lambda: 2016)
    return log


def test_load_years_scans_every_month_of_those_years(downloads: list[tuple[str, str]]) -> None:
    usage = ss.load("usage", years=range(2014, 2016)).collect()
    assert usage["month"].unique().sort().to_list() == ["2014-11", "2014-12", "2015-01", "2015-02"]
    assert downloads == [
        ("complete-2014", "files.parquet"),
        ("complete-2015", "files.parquet"),
        ("complete-2014", "usage/2014-11.parquet"),
        ("complete-2014", "usage/2014-12.parquet"),
        ("complete-2015", "usage/2015-01.parquet"),
        ("complete-2015", "usage/2015-02.parquet"),
    ]


def test_load_without_years_takes_everything(downloads: list[tuple[str, str]]) -> None:
    assert ss.load("usage").collect()["month"].unique().sort().to_list() == MONTHS


def test_load_months_downloads_only_those_months(downloads: list[tuple[str, str]]) -> None:
    usage = ss.load("usage", months=["2016-02-H1", "2014-12"]).collect()
    assert usage["month"].unique().sort().to_list() == ["2014-12", "2016-02-H1"]
    assert [file for _, file in downloads if file.startswith("usage/")] == [
        "usage/2014-12.parquet",
        "usage/2016-02-H1.parquet",
    ]


def test_load_filters_formats_and_cutoffs(downloads: list[tuple[str, str]]) -> None:
    usage = ss.load("usage", months=["2014-11"], formats=["ou"], cutoffs=[1500]).collect()
    assert usage.select("format", "cutoff").rows() == [("ou", 1500)]


def test_table_missing_some_years_is_read_where_it_exists(downloads: list[tuple[str, str]]) -> None:
    assert ss.load("mega").collect()["month"].unique().sort().to_list() == ["2014-11", "2014-12"]


def test_unknown_table_lists_the_tables(downloads: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError, match=r"no 'usag' table in 2014\.\.2016; tables there: \['mega', 'usage'\]"):
        ss.load("usag")


def test_table_absent_from_the_years_asked(downloads: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError, match=r"no 'mega' table in 2015\.\.2016; tables there: \['usage'\]"):
        ss.load("mega", years=[2015, 2016])


def test_month_without_data_lists_the_months(downloads: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError, match=r"'usage' has no data for \['2015-07'\]; months it has in 2015\.\.2015"):
        ss.load("usage", months=["2015-01", "2015-07"])
    assert not [file for _, file in downloads if file.startswith("usage/")]


@pytest.mark.parametrize("years", [[2013], [2015, 2017]])
def test_year_without_dataset(downloads: list[tuple[str, str]], years: list[int]) -> None:
    with pytest.raises(ValueError, match="one per year from 2014 to 2016"):
        ss.load("usage", years=years)
    assert downloads == []


def test_years_and_months_together_are_refused(downloads: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError, match="years or months"):
        ss.load("usage", years=[2015], months=["2015-01"])


def test_pokemon_comes_from_the_latest_year(downloads: list[tuple[str, str]]) -> None:
    assert ss.load("pokemon").collect()["pokedex_of"].to_list() == [2016]
    assert ss.load("pokemon", years=[2014, 2015]).collect()["pokedex_of"].to_list() == [2015]
    assert downloads == [("complete-2016", "pokemon.parquet"), ("complete-2015", "pokemon.parquet")]


def test_formats_are_concatenated_over_the_years(downloads: list[tuple[str, str]]) -> None:
    assert ss.load("formats", years=[2014, 2015]).collect()["month"].to_list() == MONTHS[:4]
    assert ss.load("formats", months=["2015-02"]).collect()["month"].to_list() == ["2015-02"]


def test_load_lite(downloads: list[tuple[str, str]]) -> None:
    assert ss.load_lite("usage", formats=["uu"]).collect()["format"].to_list() == ["uu"]
    assert downloads == [("lite", "usage.parquet")]


def test_load_lite_unknown_table_lists_the_tables(downloads: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError, match="no 'teammates' table in the Lite dataset; it has: pokemon, formats"):
        ss.load_lite("teammates")


def test_a_local_copy_is_read_without_downloading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "lite").mkdir()
    pl.DataFrame({"format": ["gen9ou", "gen9uu"]}).write_parquet(tmp_path / "lite/usage.parquet")
    monkeypatch.setenv("SMOGON_STATS_DIR", str(tmp_path))

    assert reader.download(reader.COMPLETE.format(year=2024), "usage/2024-01.parquet") == (
        tmp_path / "complete-2024/usage/2024-01.parquet"
    )
    assert ss.load_lite("usage", formats=["gen9uu"]).collect()["format"].to_list() == ["gen9uu"]


def test_files_lists_what_each_year_holds(downloads: list[tuple[str, str]]) -> None:
    index = ss.load("files", years=[2014, 2015]).collect()
    assert index.columns == ["table", "month"]
    assert set(index["table"]) == {"usage", "mega"}


def test_a_kaggle_notebook_mounts_each_dataset_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked = []

    def fake_dataset_download(dataset: str) -> str:
        asked.append(dataset)
        return str(tmp_path / dataset.split("/")[1])

    monkeypatch.setenv("KAGGLE_KERNEL_RUN_TYPE", "Batch")
    monkeypatch.delenv("SMOGON_STATS_DIR", raising=False)
    monkeypatch.setattr(reader.kagglehub, "dataset_download", fake_dataset_download)
    reader._mounted.cache_clear()
    year = reader.COMPLETE.format(year=2024)

    assert reader.download(year, "usage/2024-01.parquet") == (
        tmp_path / "smogon-usage-stats-complete-2024/usage/2024-01.parquet"
    )
    reader.download(year, "usage/2024-02.parquet")
    assert asked == [year]
