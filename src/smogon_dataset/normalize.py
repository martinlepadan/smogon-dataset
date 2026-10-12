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

    chaos_pokemon, weights, checks = scan("chaos_pokemon"), scan("chaos_weights"), scan("chaos_checks")
    repeated = repeated_entries(chaos_pokemon)
    if repeated.height:
        weights = weights.join(repeated.lazy(), on=[*KEYS, "pokemon"], how="anti")
        checks = checks.join(repeated.lazy(), on=[*KEYS, "pokemon"], how="anti")
    usage, leads = scan("usage"), scan("leads")
    tables = {
        "cutoffs": cutoffs(usage, leads, scan("metagame_stalliness")),
        "usage": _one_row_per_pokemon(usage, ["usage_pct", "raw", "raw_pct", "real", "real_pct"]),
        "leads": _one_row_per_pokemon(leads, ["usage_pct", "raw", "raw_pct"]),
        "movesets": movesets(chaos_pokemon),
        "abilities": _weights(weights, "abilities", "ability"),
        "items": _weights(weights, "items", "item"),
        "moves": _weights(weights, "moves", "move"),
        "tera_types": _weights(weights, "tera_types", "tera_type"),
        "happiness": happiness(weights),
        "spreads": spreads(weights),
        "teammates": teammates(weights, month_dir.name, repeated),
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


def happiness(weights: pl.LazyFrame) -> pl.LazyFrame:
    # The game caps happiness at 255, but hackmons players type in anything: 127.5, 1e+308,
    # or nothing at all, which Smogon writes "null" or "None". Hence a float, and nulls.
    value = pl.col("happiness").replace({"null": None, "None": None}).cast(pl.Float64)
    return _weights(weights, "happiness", "happiness").with_columns(value)


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


def teammates(weights: pl.LazyFrame, month: str, repeated: pl.DataFrame) -> pl.LazyFrame:
    """Same key in the source, two meanings: each gets its own column, the other stays null."""
    is_count = month >= TEAMMATES_COUNT_SINCE
    nothing = pl.lit(None, pl.Float32)
    pairs = weights.filter(pl.col("section") == "teammates").select(
        *KEYS,
        _id("pokemon"),
        # "empty" is the free slot of a team of fewer than six, not a Pokémon.
        pl.when(pl.col("key") != "empty").then(_id("key")).alias("teammate_id"),
        (nothing if is_count else pl.col("weight")).alias("association_score"),
        (pl.col("weight") if is_count else nothing).alias("count"),
    )
    if repeated.is_empty():
        return pairs
    # Only the formats with a name spelled two ways need the group-by, which is costly on this table.
    # Whole formats, not files: at some cutoffs the name is doubled among the teammates only.
    formats = repeated.select("format").unique().lazy()
    merged = (
        pairs.join(formats, on="format", how="semi")
        .group_by(*KEYS, "pokemon_id", "teammate_id", maintain_order=True)
        .agg(_total("association_score"), _total("count"))
    )
    return pl.concat([pairs.join(formats, on="format", how="anti"), merged])
