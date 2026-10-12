"""Turn the canonical tables of one month into the tables of the Complete dataset.

The canonical tables say what Smogon wrote. Here they get their meaning: Pokémon names
become `pokemon_id`, the weights table is split into one table per kind of thing, spreads
into nature and EVs, teammates into a score or a count depending on the era.
"""

import shutil
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from smogon_dataset.config import COMPLETE_DIR
from smogon_dataset.pokedex import pokemon_id, unknown_names
from smogon_dataset.validate import check_table

KEYS = ["month", "format", "cutoff"]
EVS = ["hp_ev", "atk_ev", "def_ev", "spa_ev", "spd_ev", "spe_ev"]

# Until 2021-03 Smogon publishes how much more often two Pokémon are teamed up than their
# usage predicts (negative when they avoid each other). From 2021-04 it is the weighted
# number of teams with both. Checked on every month: no negative value after the switch.
TEAMMATES_COUNT_SINCE = "2021-04"

# chaos_weights is read, split and checked this many rows at a time. Left to the lazy
# engine, the spreads of 2016-12 alone need 7 GB of memory.
BATCH_ROWS = 1_000_000


class UnknownPokemonError(Exception):
    pass


def is_normalized(month: str, out_dir: Path = COMPLETE_DIR) -> bool:
    return (out_dir / month).exists()


def normalize_month(
    month_dir: Path, pokemon: pl.DataFrame, formats: pl.DataFrame, out_dir: Path = COMPLETE_DIR
) -> None:
    """Write <out_dir>/<month>/<table>.parquet from the canonical tables in `month_dir`.

    Every table goes through validate.check_table on its way out: a month that breaks a
    rule raises and is not written.
    """
    month = month_dir.name
    unknown = unknown_names(pokemon, month_dir)["name"].to_list()
    if unknown:
        raise UnknownPokemonError(f"{month}: names missing from the pokemon table (see pokedex.RENAMED): {unknown}")
    pokemon_ids = pokemon["pokemon_id"]
    month_formats = formats.filter(pl.col("month") == month)["format"]

    # Same trick as sync: a <month> folder is always complete.
    tmp = out_dir / f"{month}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    repeated = repeated_entries(pl.scan_parquet(month_dir / "chaos_pokemon.parquet"))
    for name, table in month_tables(month_dir, repeated).items():
        written = tmp / f"{name}.parquet"
        table.sink_parquet(written, compression="zstd", compression_level=10)
        check_table(name, pl.read_parquet(written), pokemon_ids, month_formats)

    writers: dict[str, pq.ParquetWriter] = {}
    for batch in pq.ParquetFile(month_dir / "chaos_weights.parquet").iter_batches(batch_size=BATCH_ROWS):
        weights = pl.DataFrame(pl.from_arrow(batch)).join(repeated, on=[*KEYS, "pokemon"], how="anti")
        for name, part in weight_tables(weights, month).items():
            # Teammates of a format with a name spelled two ways are only unique once merged, below.
            checked = part.filter(~pl.col("format").is_in(repeated["format"].implode()))
            check_table(name, checked if name == "teammates" else part, pokemon_ids, month_formats)
            arrow = part.to_arrow()
            if name not in writers:
                writers[name] = pq.ParquetWriter(
                    tmp / f"{name}.parquet", arrow.schema, compression="zstd", compression_level=10
                )
            writers[name].write_table(arrow)
    for writer in writers.values():
        writer.close()
    if repeated.height:
        merge_repeated_teammates(tmp / "teammates.parquet", repeated)

    shutil.rmtree(out_dir / month, ignore_errors=True)
    tmp.rename(out_dir / month)


def month_tables(month_dir: Path, repeated: pl.DataFrame) -> dict[str, pl.LazyFrame]:
    """Every Complete table of a month but the seven cut out of chaos_weights (see weight_tables)."""

    def scan(name: str) -> pl.LazyFrame:
        return pl.scan_parquet(month_dir / f"{name}.parquet")

    checks = scan("chaos_checks").join(repeated.lazy(), on=[*KEYS, "pokemon"], how="anti")
    usage, leads = scan("usage"), scan("leads")
    tables = {
        "cutoffs": cutoffs(scan("chaos_info"), usage, leads, scan("metagame_stalliness")),
        "usage": _one_row_per_pokemon(usage, ["usage_pct", "raw", "raw_pct", "real", "real_pct"]),
        "leads": _one_row_per_pokemon(leads, ["usage_pct", "raw", "raw_pct"]),
        "movesets": movesets(scan("chaos_pokemon")),
        "checks_counters": checks.select(*KEYS, _id("pokemon"), _id("opponent", "opponent_id"), "n", "p", "d"),
        "metagame_styles": scan("metagame"),
        "stalliness": scan("metagame_stalliness").select(*KEYS, "bin", "hashes"),
    }
    # Only some months have these.
    if (month_dir / "mega.parquet").exists():
        tables["mega"] = scan("mega").select(*KEYS, _id("pokemon"), "pct")
    for name in ("monotype_matchups", "monotype_type_ranking"):
        if (month_dir / f"{name}.parquet").exists():
            # The files are called gen9monotype-matchup_chart-0.txt: the format is gen9monotype.
            tables[name] = scan(name).with_columns(pl.col("format").str.strip_suffix("-matchup_chart"))
    return tables


def weight_tables(weights: pl.DataFrame, month: str) -> dict[str, pl.DataFrame]:
    return {
        "abilities": _weights(weights, "abilities", "ability"),
        "items": _weights(weights, "items", "item"),
        "moves": _weights(weights, "moves", "move"),
        "tera_types": _weights(weights, "tera_types", "tera_type"),
        "happiness": happiness(weights),
        "spreads": spreads(weights),
        "teammates": teammates(weights, month),
    }


def _id(column: str, alias: str = "pokemon_id") -> pl.Expr:
    return pokemon_id(pl.col(column)).alias(alias)


def _total(column: str) -> pl.Expr:
    """Sum of a group, null rather than 0 when the group holds nothing but nulls."""
    return pl.when(pl.col(column).is_not_null().any()).then(pl.col(column).sum()).alias(column)


def repeated_entries(chaos_pokemon: pl.LazyFrame) -> pl.DataFrame:
    """Chaos entries that repeat another entry of the same file under a second spelling.

    2022-02 has both Venomicon and venomicon in two formats. Their moveset data is the
    same data twice, so the second entry is dropped. Their usage, and their weights as
    teammates of other Pokémon, are split between the two names and get added up.
    """
    return (
        chaos_pokemon.select(*KEYS, "pokemon", _id("pokemon"))
        .sort(*KEYS, "pokemon")
        .filter(~pl.col("pokemon_id").is_first_distinct().over(*KEYS, "pokemon_id"))
        .select(*KEYS, "pokemon")
        .collect()
    )


def _one_row_per_pokemon(ranking: pl.LazyFrame, summed: list[str]) -> pl.LazyFrame:
    """usage and leads keyed by pokemon_id, the rows of two spellings of one name added up."""
    return (
        ranking.with_columns(_id("pokemon"))
        .group_by(*KEYS, "pokemon_id", maintain_order=True)
        .agg(pl.col("rank").min(), *[_total(column) for column in summed])
    )


def _weights(weights: pl.DataFrame, section: str, key: str) -> pl.DataFrame:
    return weights.filter(pl.col("section") == section).select(
        *KEYS, _id("pokemon"), pl.col("key").alias(key), "weight"
    )


def cutoffs(
    chaos_info: pl.LazyFrame, usage: pl.LazyFrame, leads: pl.LazyFrame, stalliness: pl.LazyFrame
) -> pl.LazyFrame:
    """What the files say once per (month, format, cutoff) rather than once per Pokémon."""
    # A usage file with 0 battles has no row to carry that 0, and a few formats have no chaos file.
    battles = pl.concat([chaos_info.select(*KEYS, "battles"), usage.select(*KEYS, "battles")]).unique()
    return (
        battles.join(
            usage.select(*KEYS, pl.col("avg_weight").alias("avg_weight_per_team")).unique(),
            on=KEYS,
            how="full",
            coalesce=True,
        )
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
    ceiling = pl.col("viability_ceiling").first().list
    return (
        chaos_pokemon.with_columns(_id("pokemon"))
        .group_by(*KEYS, "pokemon_id", maintain_order=True)
        .agg(
            pl.col("raw_count").first(),
            _total("usage"),
            ceiling.get(0, null_on_oob=True).alias("players"),
            ceiling.get(1, null_on_oob=True).alias("gxe_top"),
            ceiling.get(2, null_on_oob=True).alias("gxe_p99"),
            ceiling.get(3, null_on_oob=True).alias("gxe_p95"),
        )
    )


def happiness(weights: pl.DataFrame) -> pl.DataFrame:
    # The game caps happiness at 255, but hackmons players type in anything: 127.5, 1e+308,
    # or nothing at all, which Smogon writes "null" or "None". Hence a float, and nulls.
    value = pl.col("happiness").replace({"null": None, "None": None}).cast(pl.Float64)
    return _weights(weights, "happiness", "happiness").with_columns(value)


def spreads(weights: pl.DataFrame) -> pl.DataFrame:
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


def teammates(weights: pl.DataFrame, month: str) -> pl.DataFrame:
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


def merge_repeated_teammates(teammates_file: Path, repeated: pl.DataFrame) -> None:
    """Add up the weights of a teammate listed under two spellings, rewriting the file in place."""
    pairs = pl.scan_parquet(teammates_file)
    # Whole formats, not files: at some cutoffs the name is doubled among the teammates only.
    formats = repeated.select("format").unique().lazy()
    merged = (
        pairs.join(formats, on="format", how="semi")
        .group_by(*KEYS, "pokemon_id", "teammate_id", maintain_order=True)
        .agg(_total("association_score"), _total("count"))
    )
    rewritten = teammates_file.with_suffix(".merged")
    pl.concat([pairs.join(formats, on="format", how="anti"), merged]).sink_parquet(
        rewritten, compression="zstd", compression_level=10
    )
    rewritten.replace(teammates_file)
