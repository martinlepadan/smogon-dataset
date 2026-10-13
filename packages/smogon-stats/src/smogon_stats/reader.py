import os
from collections.abc import Collection, Iterable
from datetime import date, timedelta
from functools import cache
from pathlib import Path
from typing import Literal

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


def load(  # noqa: PLR0913
    table: str,
    *,
    years: Iterable[int] | None = None,
    months: Collection[str] | None = None,
    formats: Collection[str] | None = None,
    family: str | None = None,
    cutoffs: Collection[int] | Literal["standard"] | None = None,
    include_special_months: bool = False,
) -> pl.LazyFrame:
    """Scan one table of the Complete dataset over `years`, or over `months` like "2024-01".

    `family` keeps a tier under all the names it had ("lc": lc, gen7lc, gen8lc...), `cutoffs="standard"`
    the standard cutoff of each format. Partial months like 2020-11-H1 repeat battles of the whole
    month: they are left out unless named in `months` or `include_special_months` is set.
    """
    years = _checked_years(years, months)

    if table == "pokemon":
        if not (formats is None and family is None and cutoffs is None):
            raise ValueError("'pokemon' has no format or cutoff to filter on")
        # Each year ships the full pokedex of its last publication, so the newest one covers the others.
        pokemon_file = download(COMPLETE.format(year=years[-1]), "pokemon.parquet")
        return pl.scan_parquet(pokemon_file)
    if table == "formats":
        if cutoffs is not None:
            raise ValueError("'formats' has no cutoff to filter on: its standard_cutoff column names the standard one")
        format_files = [download(COMPLETE.format(year=year), "formats.parquet") for year in years]
        formats_lf = _filtered(pl.scan_parquet(format_files), months, formats, None)
        if family is not None:
            formats_lf = formats_lf.filter(pl.col("family") == family)
        if months is None and not include_special_months:
            formats_lf = formats_lf.filter(~pl.col("is_special_month"))
        return formats_lf
    if table == "files":
        # The index of what each year holds: one row per table and month.
        indexes = [download(COMPLETE.format(year=year), "files.parquet") for year in years]
        return _filtered(pl.scan_parquet(indexes), months, None, None)

    month_files = _month_files(table, years, months, include_special_months)
    table_lf = _filtered(pl.scan_parquet(month_files), None, formats, None if cutoffs == "standard" else cutoffs)
    if family is None and cutoffs != "standard":
        return table_lf

    year_formats = pl.concat(pl.read_parquet(download(COMPLETE.format(year=year), "formats.parquet")) for year in years)
    if family is not None:
        family_formats = year_formats.filter(pl.col("family") == family)["format"].unique().sort().to_list()
        if not family_formats:
            raise ValueError(
                f"no format of family {family!r} in {years[0]}..{years[-1]}; "
                'the `family` column of load("formats") lists them'
            )
        # A format name never changes family, so filtering on names is exact and prunes the parquet scan.
        table_lf = table_lf.filter(pl.col("format").is_in(family_formats))
    if cutoffs == "standard":
        standard_cutoffs = year_formats.lazy().select("month", "format", pl.col("standard_cutoff").alias("cutoff"))
        table_lf = table_lf.join(standard_cutoffs, on=["month", "format", "cutoff"], how="semi")
    return table_lf


def _month_files(
    table: str, years: list[int], months: Collection[str] | None, include_special_months: bool
) -> list[Path]:
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
    elif not include_special_months:
        # A special month is the only kind with a suffix after YYYY-MM; no need to fetch `formats` to tell.
        table_months = [month for month in table_months if len(month) == 7]

    # 2020-11-H1 or 2023-09-DLC1 live in the dataset of their first four characters.
    return [download(COMPLETE.format(year=month[:4]), f"{table}/{month}.parquet") for month in table_months]


def load_lite(
    table: str,
    *,
    years: Iterable[int] | None = None,
    months: Collection[str] | None = None,
    formats: Collection[str] | None = None,
) -> pl.LazyFrame:
    """Scan one table of the Lite dataset."""
    if table not in LITE_TABLES:
        raise ValueError(f"no {table!r} table in the Lite dataset; it has: {', '.join(LITE_TABLES)}")
    if years is not None and months is not None:
        raise ValueError("pass years or months, not both")
    table_lf = _filtered(pl.scan_parquet(download(LITE, f"{table}.parquet")), months, formats, None)
    if years is not None:
        table_lf = table_lf.filter(pl.col("month").str.slice(0, 4).is_in([str(year) for year in years]))
    return table_lf


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
