import os
from collections.abc import Collection, Iterable
from datetime import date, timedelta
from functools import cache
from pathlib import Path

import kagglehub
import polars as pl

DATASET_PREFIX = "martinlepadan/smogon-usage-stats-"
LITE = DATASET_PREFIX + "lite"
COMPLETE = DATASET_PREFIX + "complete-{year}"
FIRST_YEAR = 2014
LITE_TABLES = ("pokemon", "formats", "cutoffs", "usage", "abilities", "items", "moves", "tera_types")


def download(dataset: str, file: str) -> Path:
    # With a copy of the datasets on disk, laid out as on Kaggle (lite/, complete-2024/...), nothing is fetched.
    if local_copy := os.environ.get("SMOGON_STATS_DIR"):
        return Path(local_copy) / dataset.removeprefix(DATASET_PREFIX) / file
    if "KAGGLE_KERNEL_RUN_TYPE" in os.environ:
        return _mounted(dataset) / file
    # One file per call: kagglehub answers 404 on a folder, and a whole year weighs 2 to 3 GB.
    return Path(kagglehub.dataset_download(dataset, path=file))


@cache
def _mounted(dataset: str) -> Path:
    # A Kaggle notebook mounts a dataset instead of downloading it, and refuses more than a few
    # dozen requests in a row: ask once per dataset, not once per file.
    return Path(kagglehub.dataset_download(dataset))


def load(
    table: str,
    *,
    years: Iterable[int] | None = None,
    months: Collection[str] | None = None,
    formats: Collection[str] | None = None,
    cutoffs: Collection[int] | None = None,
) -> pl.LazyFrame:
    """Scan one table of the Complete dataset over `years`, or over `months` like "2024-01"."""
    years = _checked_years(years, months)

    if table == "pokemon":
        # Each year ships the full pokedex of its last publication, so the newest one covers the others.
        pokemon_file = download(COMPLETE.format(year=years[-1]), "pokemon.parquet")
        return _filtered(pl.scan_parquet(pokemon_file), None, formats, cutoffs)
    if table == "formats":
        format_files = [download(COMPLETE.format(year=year), "formats.parquet") for year in years]
        return _filtered(pl.scan_parquet(format_files), months, formats, cutoffs)
    if table == "files":
        # The index of what each year holds: one row per table and month.
        indexes = [download(COMPLETE.format(year=year), "files.parquet") for year in years]
        return _filtered(pl.scan_parquet(indexes), months, None, None)

    published = pl.concat(pl.read_parquet(download(COMPLETE.format(year=year), "files.parquet")) for year in years)
    table_months = published.filter(pl.col("table") == table)["month"].sort().to_list()
    if not table_months:
        raise ValueError(
            f"no {table!r} table in {years[0]}..{years[-1]}; tables there: {sorted(set(published['table']))}"
        )
    if months is not None:
        absent = sorted(set(months) - set(table_months))
        if absent:
            raise ValueError(
                f"{table!r} has no data for {absent}; months it has in {years[0]}..{years[-1]}: {table_months}"
            )
        table_months = [month for month in table_months if month in months]

    # 2020-11-H1 or 2023-09-DLC1 live in the dataset of their first four characters.
    month_files = [download(COMPLETE.format(year=month[:4]), f"{table}/{month}.parquet") for month in table_months]
    return _filtered(pl.scan_parquet(month_files), None, formats, cutoffs)


def load_lite(table: str, *, formats: Collection[str] | None = None) -> pl.LazyFrame:
    """Scan one table of the Lite dataset."""
    if table not in LITE_TABLES:
        raise ValueError(f"no {table!r} table in the Lite dataset; it has: {', '.join(LITE_TABLES)}")
    return _filtered(pl.scan_parquet(download(LITE, f"{table}.parquet")), None, formats, None)


def _latest_year() -> int:
    # Smogon publishes a month once it is over: in January the newest data is still last year's.
    return (date.today().replace(day=1) - timedelta(days=1)).year


def _checked_years(years: Iterable[int] | None, months: Collection[str] | None) -> list[int]:
    if years is not None and months is not None:
        raise ValueError("pass years or months, not both")
    latest = _latest_year()
    if months is not None:
        asked = sorted({int(month[:4]) for month in months})
    elif years is not None:
        asked = sorted(set(years))
    else:
        asked = list(range(FIRST_YEAR, latest + 1))
    unpublished = [year for year in asked if not FIRST_YEAR <= year <= latest]
    if unpublished:
        raise ValueError(f"no Complete dataset for {unpublished}: there is one per year from {FIRST_YEAR} to {latest}")
    return asked


def _filtered(
    table_lf: pl.LazyFrame,
    months: Collection[str] | None,
    formats: Collection[str] | None,
    cutoffs: Collection[int] | None,
) -> pl.LazyFrame:
    if months is not None:
        table_lf = table_lf.filter(pl.col("month").is_in(months))
    if formats is not None:
        table_lf = table_lf.filter(pl.col("format").is_in(formats))
    if cutoffs is not None:
        table_lf = table_lf.filter(pl.col("cutoff").is_in(cutoffs))
    return table_lf
