"""Turn the canonical tables of one month into the tables of the Complete dataset.

The canonical tables say what Smogon wrote. Here they get their meaning: Pokémon names
become `pokemon_id`, the weights table is split into one table per kind of thing, spreads
into nature and EVs, teammates into a score or a count depending on the era.
"""

import shutil
from pathlib import Path

import polars as pl

from smogon_dataset.config import COMPLETE_DIR
from smogon_dataset.pokedex import pokemon_id, unknown_names

KEYS = ["month", "format", "cutoff"]
EVS = ["hp_ev", "atk_ev", "def_ev", "spa_ev", "spd_ev", "spe_ev"]

# Until 2021-03 Smogon publishes how much more often two Pokémon are teamed up than their
# usage predicts (negative when they avoid each other). From 2021-04 it is the weighted
# number of teams with both. Checked on every month: no negative value after the switch.
TEAMMATES_COUNT_SINCE = "2021-04"


class UnknownPokemonError(Exception):
    pass


def is_normalized(month: str, out_dir: Path = COMPLETE_DIR) -> bool:
    return (out_dir / month).exists()


def normalize_month(month_dir: Path, pokemon: pl.DataFrame, out_dir: Path = COMPLETE_DIR) -> None:
    """Write <out_dir>/<month>/<table>.parquet from the canonical tables in `month_dir`."""
    month = month_dir.name
    unknown = unknown_names(pokemon, month_dir)["name"].to_list()
    if unknown:
        raise UnknownPokemonError(f"{month}: names missing from the pokemon table (see pokedex.RENAMED): {unknown}")

    # Same trick as sync: a <month> folder is always complete.
    tmp = out_dir / f"{month}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, table in month_tables(month_dir).items():
        table.sink_parquet(tmp / f"{name}.parquet", compression="zstd", compression_level=10)
    shutil.rmtree(out_dir / month, ignore_errors=True)
    tmp.rename(out_dir / month)


def month_tables(month_dir: Path) -> dict[str, pl.LazyFrame]:
    """The Complete tables of a month, as lazy queries so that nothing big is held in memory."""

    def scan(name: str) -> pl.LazyFrame:
        return pl.scan_parquet(month_dir / f"{name}.parquet")

    weights = scan("chaos_weights")
    usage = scan("usage")
    tables = {
        "cutoffs": cutoffs(usage, scan("leads"), scan("metagame_stalliness")),
        "usage": usage.select(*KEYS, _id("pokemon"), "rank", "usage_pct", "raw", "raw_pct", "real", "real_pct"),
        "leads": scan("leads").select(*KEYS, _id("pokemon"), "rank", "usage_pct", "raw", "raw_pct"),
        "movesets": movesets(scan("chaos_pokemon")),
        "abilities": _weights(weights, "abilities", "ability"),
        "items": _weights(weights, "items", "item"),
        "moves": _weights(weights, "moves", "move"),
        "tera_types": _weights(weights, "tera_types", "tera_type"),
        # Int64: hackmons players type in values like 744444444444444500.
        "happiness": _weights(weights, "happiness", "happiness").with_columns(pl.col("happiness").cast(pl.Int64)),
        "spreads": spreads(weights),
        "teammates": teammates(weights, month_dir.name),
        "checks_counters": scan("chaos_checks").select(
            *KEYS, _id("pokemon"), _id("opponent", "opponent_id"), "n", "p", "d"
        ),
        "metagame_styles": scan("metagame"),
        "stalliness": scan("metagame_stalliness").select(*KEYS, "bin", "hashes"),
    }
    # Only some months have these.
    if (month_dir / "mega.parquet").exists():
        tables["mega"] = scan("mega").select(*KEYS, _id("pokemon"), "pct")
    for name in ("monotype_matchups", "monotype_type_ranking"):
        if (month_dir / f"{name}.parquet").exists():
            tables[name] = scan(name)
    return tables


def _id(column: str, alias: str = "pokemon_id") -> pl.Expr:
    return pokemon_id(pl.col(column)).alias(alias)


def _weights(weights: pl.LazyFrame, section: str, key: str) -> pl.LazyFrame:
    return weights.filter(pl.col("section") == section).select(
        *KEYS, _id("pokemon"), pl.col("key").alias(key), "weight"
    )


def cutoffs(usage: pl.LazyFrame, leads: pl.LazyFrame, stalliness: pl.LazyFrame) -> pl.LazyFrame:
    """What the files say once per (month, format, cutoff) rather than once per Pokémon."""
    return (
        usage.select(*KEYS, "battles", pl.col("avg_weight").alias("avg_weight_per_team"))
        .unique()
        .join(leads.select(*KEYS, "total_leads").unique(), on=KEYS, how="full", coalesce=True)
        .join(
            stalliness.select(*KEYS, pl.col("mean").alias("stalliness_mean"), "pct_per_hash").unique(),
            on=KEYS,
            how="full",
            coalesce=True,
        )
        .sort(KEYS)
    )


def movesets(chaos_pokemon: pl.LazyFrame) -> pl.LazyFrame:
    # Viability Ceiling is [players who used it, best GXE among them, 99th percentile, 95th percentile].
    ceiling = pl.col("viability_ceiling").list
    return chaos_pokemon.select(
        *KEYS,
        _id("pokemon"),
        "raw_count",
        "usage",
        ceiling.get(0, null_on_oob=True).alias("players"),
        ceiling.get(1, null_on_oob=True).alias("gxe_top"),
        ceiling.get(2, null_on_oob=True).alias("gxe_p99"),
        ceiling.get(3, null_on_oob=True).alias("gxe_p95"),
    )


def spreads(weights: pl.LazyFrame) -> pl.LazyFrame:
    """'Adamant:252/0/4/0/0/252' -> nature and the six EVs, in Showdown's order."""
    nature_evs = pl.col("key").str.split_exact(":", 1)
    evs = nature_evs.struct.field("field_1").str.split_exact("/", 5)
    return weights.filter(pl.col("section") == "spreads").select(
        *KEYS,
        _id("pokemon"),
        nature_evs.struct.field("field_0").alias("nature"),
        *[evs.struct.field(f"field_{i}").cast(pl.Int32).alias(ev) for i, ev in enumerate(EVS)],
        "weight",
    )


def teammates(weights: pl.LazyFrame, month: str) -> pl.LazyFrame:
    """Same key in the source, two meanings: each gets its own column, the other stays null."""
    is_count = month >= TEAMMATES_COUNT_SINCE
    nothing = pl.lit(None, pl.Float32)
    return weights.filter(pl.col("section") == "teammates").select(
        *KEYS,
        _id("pokemon"),
        # "empty" is the free slot of a team of fewer than six, not a Pokémon.
        pl.when(pl.col("key") != "empty").then(_id("key")).alias("teammate_id"),
        (nothing if is_count else pl.col("weight")).alias("association_score"),
        (pl.col("weight") if is_count else nothing).alias("count"),
    )
