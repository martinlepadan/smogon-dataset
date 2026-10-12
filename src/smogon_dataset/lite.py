"""The Lite dataset: the Complete tables cut down to the Lite series, at their standard cutoff."""

import shutil
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from smogon_dataset.config import LITE_DIR

KEYS = ["month", "format", "cutoff"]
TABLES = ("cutoffs", "usage", "abilities", "items", "moves", "tera_types")
WEIGHT_TABLES = ("abilities", "items", "moves", "tera_types")
# Below this share of a Pokémon's sets a row is dropped. The long tail is half the moves
# and two thirds of the items, and it stays in the Complete dataset.
MIN_PCT = 0.1


class MissingFromLiteError(Exception):
    pass


def lite_formats(formats: pl.DataFrame) -> pl.DataFrame:
    # A DLC or half-month folder is a slice of a month that is also published whole:
    # keeping both would count those battles twice in every series.
    return formats.filter(pl.col("lite_series").is_not_null() & ~pl.col("is_special_month"))


def build_lite(complete_dir: Path, pokemon: pl.DataFrame, formats: pl.DataFrame, out_dir: Path = LITE_DIR) -> None:
    """Write <out_dir>/<table>.parquet and .csv, one file per table over every normalized month."""
    normalized = [path.name for path in complete_dir.iterdir() if path.suffix != ".part"]
    kept = lite_formats(formats).filter(pl.col("month").is_in(normalized)).sort("month", "format")

    tmp = out_dir.with_name(out_dir.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    pokemon.write_parquet(tmp / "pokemon.parquet")
    kept.write_parquet(tmp / "formats.parquet")
    for name in TABLES:
        # One month at a time, or the whole Complete goes through memory.
        months = (
            _lite_rows(complete_dir / str(month), name, month_formats).to_arrow()
            for (month,), month_formats in kept.group_by("month", maintain_order=True)
        )
        first = next(months)
        with pq.ParquetWriter(
            tmp / f"{name}.parquet", first.schema, compression="zstd", compression_level=10
        ) as writer:
            writer.write_table(first)
            for rows in months:
                writer.write_table(rows)
    for written in sorted(tmp.glob("*.parquet")):
        pl.scan_parquet(written).sink_csv(written.with_suffix(".csv"))

    # Every Lite format was played, so each must have come out with a usage ranking.
    files = kept.select("month", "format", pl.col("standard_cutoff").alias("cutoff"))
    ranked = pl.scan_parquet(tmp / "usage.parquet").select(KEYS).unique().collect()
    missing = files.join(ranked, on=KEYS, how="anti")
    if missing.height:
        raise MissingFromLiteError(f"no usage at the standard cutoff for {missing.rows()}")

    shutil.rmtree(out_dir, ignore_errors=True)
    tmp.rename(out_dir)


def _lite_rows(month_dir: Path, table: str, month_formats: pl.DataFrame) -> pl.DataFrame:
    is_kept = pl.any_horizontal(
        (pl.col("format") == name) & (pl.col("cutoff") == cutoff)
        for name, cutoff in month_formats.select("format", "standard_cutoff").iter_rows()
    )
    rows = pl.scan_parquet(month_dir / f"{table}.parquet").filter(is_kept)
    if table not in WEIGHT_TABLES:
        return rows.collect()

    # Every set has exactly one ability, so the ability weights of a Pokémon add up to the
    # weight of all its sets. Smogon's moveset reports divide by the same number: checked
    # to the third decimal against 2014-11 ou and 2015-08 ubers.
    sets = (
        pl.scan_parquet(month_dir / "abilities.parquet")
        .filter(is_kept)
        .group_by(*KEYS, "pokemon_id")
        .agg(pl.col("weight").cast(pl.Float64).sum().alias("sets"))
    )
    pct = (pl.col("weight") / pl.col("sets") * 100).round(3)
    return (
        rows.join(sets, on=[*KEYS, "pokemon_id"], maintain_order="left")
        # 0 / 0 for a Pokémon only seen far below the cutoff.
        .filter(pl.col("sets") > 0)
        .with_columns(pct=pct)
        .filter(pl.col("pct") >= MIN_PCT)
        .drop("weight", "sets")
        .collect()
    )
