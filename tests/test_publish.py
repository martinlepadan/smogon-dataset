import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from smogon_dataset.columns import COLUMNS, lite_columns
from smogon_dataset.publish import (
    LITE_TABLES,
    UndescribedColumnsError,
    stage_complete,
    stage_lite,
    write_cards,
)

TYPES = {"cutoff": pl.Int32, "usage_pct": pl.Float64, "pct": pl.Float64, "is_special_month": pl.Boolean}


def _write(path: Path, columns: dict[str, str], months: list[str | None] | None = None) -> None:
    """A table with the right columns and nothing in them but its months."""
    months = months or [None]
    schema = {column: TYPES.get(column, pl.String) for column in columns}
    rows = pl.DataFrame({column: [None] * len(months) for column in columns}, schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.with_columns(pl.Series("month", months, pl.String) if "month" in columns else []).write_parquet(path)


def _complete(tmp_path: Path, months: dict[str, list[str]]) -> Path:
    complete = tmp_path / "complete"
    for month, tables in months.items():
        for table in tables:
            _write(complete / month / f"{table}.parquet", COLUMNS[table], [month])
    (complete / ".gitkeep").touch()
    _write(tmp_path / "pokemon.parquet", COLUMNS["pokemon"])
    whole_months = [month for month in months if not month.endswith(".part")]
    _write(tmp_path / "formats.parquet", COLUMNS["formats"], [*whole_months])
    return complete


def _lite(tmp_path: Path) -> Path:
    lite = tmp_path / "lite"
    for table in LITE_TABLES:
        _write(lite / f"{table}.parquet", lite_columns(table))
        (lite / f"{table}.csv").write_text(",".join(lite_columns(table)) + "\n")
    (lite / ".gitkeep").touch()
    return lite


def _card(dataset_dir: Path) -> dict[str, Any]:
    card: dict[str, Any] = json.loads((dataset_dir / "dataset-metadata.json").read_text())
    return card


def test_stage_complete_makes_one_dataset_per_year_with_one_folder_per_table(tmp_path: Path) -> None:
    complete = _complete(
        tmp_path,
        {"2020-11": ["usage", "mega"], "2020-11-H1": ["usage"], "2021-01": ["usage"], "2021-02.part": ["usage"]},
    )
    pl.DataFrame({"tera_type": []}).write_parquet(complete / "2020-11/tera_types.parquet")
    staged = tmp_path / "kaggle"
    (staged / "complete-2019/leads").mkdir(parents=True)
    (staged / "lite").mkdir()

    year_dirs = stage_complete(complete, tmp_path / "pokemon.parquet", tmp_path / "formats.parquet", staged)

    assert [path.name for path in year_dirs] == ["complete-2020", "complete-2021"]
    assert sorted(str(path.relative_to(staged)) for path in staged.rglob("*.parquet")) == [
        "complete-2020/files.parquet",
        "complete-2020/formats.parquet",
        "complete-2020/mega/2020-11.parquet",
        "complete-2020/pokemon.parquet",
        "complete-2020/usage/2020-11-H1.parquet",
        "complete-2020/usage/2020-11.parquet",
        "complete-2021/files.parquet",
        "complete-2021/formats.parquet",
        "complete-2021/pokemon.parquet",
        "complete-2021/usage/2021-01.parquet",
    ]
    assert (staged / "complete-2020/usage/2020-11.parquet").samefile(complete / "2020-11/usage.parquet")
    assert pl.read_parquet(staged / "complete-2020/formats.parquet")["month"].to_list() == ["2020-11", "2020-11-H1"]
    # Only the Complete folders are rebuilt.
    assert not (staged / "complete-2019").exists()
    assert (staged / "lite").exists()


def test_files_parquet_lists_the_data_files_of_the_year(tmp_path: Path) -> None:
    complete = _complete(tmp_path, {"2020-11": ["usage", "mega"], "2020-11-H1": ["usage"], "2021-01": ["usage"]})
    staged = tmp_path / "kaggle"

    stage_complete(complete, tmp_path / "pokemon.parquet", tmp_path / "formats.parquet", staged)

    files = pl.read_parquet(staged / "complete-2020/files.parquet")
    assert files.schema == {"table": pl.String, "month": pl.String}
    assert files.rows() == [("mega", "2020-11"), ("usage", "2020-11"), ("usage", "2020-11-H1")]
    for table, month in files.rows():
        assert (staged / "complete-2020" / table / f"{month}.parquet").exists()


def test_a_table_with_other_columns_than_described_stops_the_staging_before_it_removes_anything(
    tmp_path: Path,
) -> None:
    complete = _complete(tmp_path, {"2020-11": ["usage"], "2021-01": ["usage"]})
    renamed = {column: "" for column in COLUMNS["movesets"]} | {"gxe_p95": ""}
    del renamed["gxe_p80"]
    _write(complete / "2021-01/movesets.parquet", renamed, ["2021-01"])
    staged = tmp_path / "kaggle"
    (staged / "complete-2019/leads").mkdir(parents=True)

    with pytest.raises(UndescribedColumnsError, match=r"2021-01/movesets\.parquet.*gxe_p95"):
        stage_complete(complete, tmp_path / "pokemon.parquet", tmp_path / "formats.parquet", staged)

    assert (staged / "complete-2019/leads").exists()
    assert not (staged / "complete-2020").exists()


def test_stage_lite_links_the_sixteen_files(tmp_path: Path) -> None:
    lite = _lite(tmp_path)
    staged = tmp_path / "kaggle"
    (staged / "lite").mkdir(parents=True)
    (staged / "lite/spreads.parquet").touch()
    (staged / "complete-2020").mkdir()

    staged_dir = stage_lite(lite, staged)

    assert staged_dir == staged / "lite"
    names = sorted(path.name for path in staged_dir.iterdir())
    assert names == sorted(f"{table}{suffix}" for table in LITE_TABLES for suffix in (".csv", ".parquet"))
    assert len(names) == 16
    assert all((staged_dir / name).samefile(lite / name) for name in names)
    assert (staged / "complete-2020").exists()


def test_stage_lite_refuses_a_weight_table_that_still_has_its_weights(tmp_path: Path) -> None:
    lite = _lite(tmp_path)
    _write(lite / "moves.parquet", COLUMNS["moves"])

    with pytest.raises(UndescribedColumnsError, match=r"moves\.parquet"):
        stage_lite(lite, tmp_path / "kaggle")


def test_cards_describe_every_column_of_the_files_kaggle_lets_us_describe(tmp_path: Path) -> None:
    complete = _complete(tmp_path, {"2020-11": ["usage", "mega"], "2021-01": ["usage"]})
    staged = tmp_path / "kaggle"
    stage_complete(complete, tmp_path / "pokemon.parquet", tmp_path / "formats.parquet", staged)
    stage_lite(_lite(tmp_path), staged)

    write_cards(staged)

    lite = _card(staged / "lite")
    assert lite["id"] == "martinlepadan/smogon-usage-stats-lite"
    assert lite["licenses"] == [{"name": "CC-BY-4.0"}]
    assert sorted(resource["path"] for resource in lite["resources"]) == sorted(
        path.name for path in (staged / "lite").iterdir() if path.name != "dataset-metadata.json"
    )
    for resource in lite["resources"]:
        table = resource["path"].split(".")[0]
        fields = resource["schema"]["fields"]
        assert [field["name"] for field in fields] == pl.read_parquet(staged / f"lite/{table}.parquet").columns
        assert all(field["description"] for field in fields)
    moves = next(resource for resource in lite["resources"] if resource["path"] == "moves.csv")
    assert [(field["name"], field["type"]) for field in moves["schema"]["fields"]] == [
        ("month", "string"),
        ("format", "string"),
        ("cutoff", "integer"),
        ("pokemon_id", "string"),
        ("move", "string"),
        ("pct", "decimal"),
    ]
    formats = next(resource for resource in lite["resources"] if resource["path"] == "formats.parquet")
    assert {"name": "is_special_month", "type": "boolean"}.items() <= formats["schema"]["fields"][7].items()

    year = _card(staged / "complete-2020")
    assert year["id"] == "martinlepadan/smogon-usage-stats-complete-2020"
    # The kaggle CLI refuses a path that is not a file of the folder, and ignores one inside a subfolder.
    assert [resource["path"] for resource in year["resources"]] == [
        "pokemon.parquet",
        "formats.parquet",
        "files.parquet",
    ]
    assert [field["name"] for field in year["resources"][2]["schema"]["fields"]] == ["table", "month"]
    assert COLUMNS["pokemon"]["bst"] == year["resources"][0]["schema"]["fields"][14]["description"]

    for card in (lite, year, _card(staged / "complete-2021")):
        assert 6 <= len(card["title"]) <= 50
        assert 20 <= len(card["subtitle"]) <= 80


def test_cards_link_to_each_other_and_a_year_describes_the_tables_it_has(tmp_path: Path) -> None:
    complete = _complete(tmp_path, {"2020-11": ["usage", "mega"], "2021-01": ["usage"]})
    staged = tmp_path / "kaggle"
    stage_complete(complete, tmp_path / "pokemon.parquet", tmp_path / "formats.parquet", staged)
    stage_lite(_lite(tmp_path), staged)

    write_cards(staged)

    datasets = "https://www.kaggle.com/datasets/martinlepadan/smogon-usage-stats"
    lite = _card(staged / "lite")["description"]
    assert f"{datasets}-complete-2020" in lite
    assert f"{datasets}-complete-2021" in lite

    year = _card(staged / "complete-2020")["description"]
    assert f"{datasets}-lite" in year
    assert f"{datasets}-complete-2021" in year
    assert f"{datasets}-complete-2020" not in year
    assert 'dataset_download("martinlepadan/smogon-usage-stats-complete-2020", path="usage/2020-11.parquet")' in year
    assert f"- `usage_pct` (decimal): {COLUMNS['usage']['usage_pct']}" in year
    # The keys are described once, except where a table gives one its own meaning.
    assert year.count(f"- `cutoff`: {COLUMNS['usage']['cutoff']}") == 1
    assert "- `cutoff` (integer)" not in year
    assert f"- `pokemon_id` (string): {COLUMNS['mega']['pokemon_id']}" in year
    assert "### mega" not in _card(staged / "complete-2021")["description"]
    assert "smogon.com/stats" in year
    assert "not affiliated" in year
