"""The `formats` table: what each format name of each month stands for."""

from pathlib import Path

import polars as pl

from smogon_dataset.config import INTERIM_DIR
from smogon_dataset.inventory import standard_cutoffs

FORMATS_PATH = INTERIM_DIR / "formats.parquet"

# Tiers whose Lite series follows the current generation: ubers, gen7ubers, gen8ubers...
LITE_TIERS = ["ubers", "uu", "ru", "nu", "doublesou", "nationaldex", "monotype", "anythinggoes"]

# Doubles OU was called Smogon Doubles until 2015-03.
FAMILY_RENAMES = {"smogondoubles": "doublesou"}

# Generations have one digit so far. "gen10ou" will need a decision: read this way it is gen 1.
_GEN_PREFIX = r"^gen(\d)"


def read_battles(interim_dir: Path) -> pl.DataFrame:
    """Battles of each (month, format), from the header of the usage files of the synced months."""
    # A <month>.part folder is a month sync is still writing: its files have no footer yet.
    usage_files = sorted(path for path in interim_dir.glob("*/usage.parquet") if path.parent.suffix != ".part")
    months = [pl.scan_parquet(path).select("month", "format", "battles").unique() for path in usage_files]
    # Same number at every cutoff: the cutoff changes the weights, not the battles counted.
    return pl.concat(months).unique().collect()


def build_formats(inventory: pl.DataFrame, battles: pl.DataFrame) -> pl.DataFrame:
    """One row per (month, format).

    `format` stays the name Smogon used that month and remains the join key. `format_id`
    is the same name with its generation spelled out, `family` the name without it, so
    that `ou`, `gen7ou` and `gen9ou` can be told apart or followed as one series.
    `lite_series` is null for the formats left out of the Lite dataset.
    """
    family = pl.col("format_id").str.replace(_GEN_PREFIX, "").replace(FAMILY_RENAMES)
    # The 1695 cutoff goes to the OU of the generation being played, which is how we know which one it is.
    current_gen = pl.col("gen").filter((pl.col("family") == "ou") & (pl.col("standard_cutoff") == 1695)).max()
    is_vgc = pl.col("family").str.contains("vgc")
    top_vgc_battles = pl.col("battles").filter(is_vgc).max().over("month")
    return (
        standard_cutoffs(inventory)
        .rename({"cutoff": "standard_cutoff"})
        .join(battles, on=["month", "format"], how="left")
        .with_columns(
            # No prefix means gen 6: Smogon only started prefixing its current generation in 2017-07.
            format_id=pl.when(pl.col("format").str.contains(_GEN_PREFIX))
            .then("format")
            .otherwise(pl.lit("gen6") + pl.col("format")),
        )
        .with_columns(gen=pl.col("format_id").str.extract(_GEN_PREFIX).cast(pl.Int32), family=family)
        .with_columns(
            current_gen=current_gen.over("month"),
            is_special_month=pl.col("month").str.len_chars() > len("2020-11"),
        )
        .with_columns(
            lite_series=pl.when(pl.col("family") == "ou")
            .then("format_id")
            .when(pl.col("family").is_in(LITE_TIERS) & (pl.col("gen") == pl.col("current_gen")))
            .then("family")
            .when(is_vgc & (pl.col("battles") == top_vgc_battles))
            .then(pl.lit("vgc"))
        )
        .select(
            "month",
            "format",
            "format_id",
            "gen",
            "family",
            "battles",
            "standard_cutoff",
            "is_special_month",
            "lite_series",
        )
        .sort("month", "format")
    )
