"""Lay the two datasets out the way they are uploaded to Kaggle, each folder with its card."""

import json
import os
import shutil
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from smogon_dataset import lite
from smogon_dataset.cards import ROOT_TABLES, complete_card, lite_card
from smogon_dataset.columns import COLUMNS, lite_columns
from smogon_dataset.config import COMPLETE_DIR, DATA_DIR, LITE_DIR
from smogon_dataset.formats import FORMATS_PATH
from smogon_dataset.pokedex import POKEMON_PATH

KAGGLE_DIR = DATA_DIR / "kaggle"
LITE_TABLES = ("pokemon", "formats", *lite.TABLES)


class UndescribedColumnsError(Exception):
    pass


def stage_complete(
    complete_dir: Path = COMPLETE_DIR,
    pokemon_path: Path = POKEMON_PATH,
    formats_path: Path = FORMATS_PATH,
    out_dir: Path = KAGGLE_DIR,
) -> list[Path]:
    """<month>/<table>.parquet becomes complete-<year>/<table>/<month>.parquet, one Kaggle dataset per year.

    A new version of a Kaggle dataset has to bring every file again. Cut by year, only the
    current one is ever sent back, and a past year can leave this disk once published.
    Inside a year it is one folder per table: Kaggle takes 50 entries at most at the root.
    """
    # Everything is checked before anything is removed: a month to normalize again leaves the last staging alone.
    staged: dict[Path, Path] = {}
    for month_dir in sorted(complete_dir.iterdir()):
        if not month_dir.is_dir() or month_dir.suffix == ".part":
            continue
        # 2020-11-H1 goes with 2020 too.
        year_dir = out_dir / f"complete-{month_dir.name[:4]}"
        for table in month_dir.iterdir():
            parquet = pq.read_metadata(table)
            # normalize writes every table every month: tera_types is empty before 2024-08.
            if parquet.num_rows == 0:
                continue
            _check_described(table, parquet.schema.names, COLUMNS[table.stem])
            staged[year_dir / table.stem / f"{month_dir.name}.parquet"] = table

    for stale in out_dir.glob("complete-*"):
        shutil.rmtree(stale)
    for link, table in staged.items():
        link.parent.mkdir(parents=True, exist_ok=True)
        # Hard links: the 30 GB are not written twice.
        os.link(table, link)

    year_dirs = sorted(out_dir.glob("complete-*"))
    formats = pl.read_parquet(formats_path)
    for year_dir in year_dirs:
        year = year_dir.name.removeprefix("complete-")
        os.link(pokemon_path, year_dir / "pokemon.parquet")
        formats.filter(pl.col("month").str.starts_with(year)).write_parquet(year_dir / "formats.parquet")
        # kagglehub cannot list a folder, so this is how a reader learns which files to ask for.
        files = sorted((link.parent.name, link.stem) for link in staged if link.parent.parent == year_dir)
        pl.DataFrame(files, schema={"table": pl.String, "month": pl.String}, orient="row").write_parquet(
            year_dir / "files.parquet"
        )
    return year_dirs


def stage_lite(lite_dir: Path = LITE_DIR, out_dir: Path = KAGGLE_DIR) -> Path:
    for table in LITE_TABLES:
        parquet = lite_dir / f"{table}.parquet"
        _check_described(parquet, pq.read_schema(parquet).names, lite_columns(table))

    staged_dir = out_dir / "lite"
    shutil.rmtree(staged_dir, ignore_errors=True)
    staged_dir.mkdir(parents=True)
    for table in LITE_TABLES:
        for suffix in (".parquet", ".csv"):
            os.link(lite_dir / f"{table}{suffix}", staged_dir / f"{table}{suffix}")
    return staged_dir


def write_cards(out_dir: Path = KAGGLE_DIR, years: list[str] | None = None) -> None:
    """Write dataset-metadata.json in the staged Lite folder and in every staged year.

    `years` are the Complete datasets the cards link to. By default the staged ones, but
    the monthly update only stages the year it adds a month to.
    """
    year_dirs = sorted(out_dir.glob("complete-*"))
    staged_years = [year_dir.name.removeprefix("complete-") for year_dir in year_dirs]
    years = years or staged_years

    lite_dir = out_dir / "lite"
    lite_schemas = {table: pl.read_parquet_schema(lite_dir / f"{table}.parquet") for table in LITE_TABLES}
    _write_card(lite_dir, lite_card(lite_schemas, years))

    for year_dir, year in zip(year_dirs, staged_years, strict=True):
        # The first file of each table: all its months have the same columns, stage_complete saw to it.
        first_month = pl.read_parquet(year_dir / "files.parquet").group_by("table", maintain_order=True).first()
        schemas = {table: pl.read_parquet_schema(year_dir / f"{table}.parquet") for table in ROOT_TABLES}
        schemas |= {
            table: pl.read_parquet_schema(year_dir / table / f"{month}.parquet") for table, month in first_month.rows()
        }
        _write_card(year_dir, complete_card(year, years, str(first_month["month"].min()), schemas))


def _check_described(table: Path, columns: list[str], described: dict[str, str]) -> None:
    if columns != list(described):
        raise UndescribedColumnsError(
            f"{table} has columns {columns} but columns.py describes {list(described)}: "
            "rebuild the file or fix the descriptions"
        )


def _write_card(dataset_dir: Path, card: dict[str, object]) -> None:
    (dataset_dir / "dataset-metadata.json").write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n")
