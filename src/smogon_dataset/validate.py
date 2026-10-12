"""What every table of the Complete dataset has to satisfy before it is written.

The parsers guarantee that nothing was lost while reading Smogon's files. This guards the
other end: that what gets published makes sense. A broken rule raises, and the month is
not written.

The bounds are what holds over the whole archive, not what one would expect: usage goes
above 100% in formats where a team can field the same species several times.
"""

import pandera.errors
import pandera.polars as pa
import polars as pl

KEYS = ["month", "format", "cutoff"]
POKEMON = [*KEYS, "pokemon_id"]
ID_COLUMNS = ["pokemon_id", "teammate_id", "opponent_id"]
NATURES = [
    "Adamant", "Bashful", "Bold", "Brave", "Calm", "Careful", "Docile", "Gentle", "Hardy", "Hasty", "Impish", "Jolly",
    "Lax", "Lonely", "Mild", "Modest", "Naive", "Naughty", "Quiet", "Quirky", "Rash", "Relaxed", "Sassy", "Serious",
    "Timid",
]  # fmt: skip
TYPES = [
    "Bug", "Dark", "Dragon", "Electric", "Fairy", "Fighting", "Fire", "Flying", "Ghost", "Grass", "Ground", "Ice",
    "Normal", "Poison", "Psychic", "Rock", "Steel", "Water",
    "Bird",  # MissingNo.
]  # fmt: skip
# Sums of rounded percentages overshoot a little: 600.0003 for a full team of six.
ROUNDING = 0.01


class ValidationError(Exception):
    pass


class PerCutoff(pa.DataFrameModel):
    month: str = pa.Field(str_matches=r"^\d{4}-\d{2}(-\w+)?$")
    format: str
    cutoff: pl.Int32 = pa.Field(isin=[0, 1500, 1630, 1695, 1760, 1825])

    class Config:
        strict = True


class PerPokemon(PerCutoff):
    pokemon_id: str


class Cutoffs(PerCutoff):
    # 0 happens: 2025-05 publishes files for a format nobody played.
    battles: pl.Int64 = pa.Field(ge=0, nullable=True)
    avg_weight_per_team: float = pa.Field(ge=0, nullable=True)
    total_leads: pl.Int64 = pa.Field(ge=0, nullable=True)
    stalliness_mean: float = pa.Field(nullable=True)
    pct_per_hash: float = pa.Field(ge=0, nullable=True)

    class Config:
        unique = KEYS


class Usage(PerPokemon):
    rank: pl.Int32 = pa.Field(ge=1)
    # Null when every team of the file weighs 0: Smogon prints NaN.
    usage_pct: float = pa.Field(ge=0, le=600, nullable=True)
    raw: pl.Int64 = pa.Field(ge=0)
    raw_pct: float = pa.Field(ge=0, le=600)
    real: pl.Int64 = pa.Field(ge=0)
    real_pct: float = pa.Field(ge=0, le=600, nullable=True)

    class Config:
        unique = POKEMON


class Leads(PerPokemon):
    rank: pl.Int32 = pa.Field(ge=1)
    usage_pct: float = pa.Field(ge=0, le=100, nullable=True)
    raw: pl.Int64 = pa.Field(ge=0)
    raw_pct: float = pa.Field(ge=0, le=100)

    class Config:
        unique = POKEMON


class Movesets(PerPokemon):
    raw_count: pl.Int64 = pa.Field(ge=0)
    usage: float = pa.Field(ge=0, le=6, nullable=True)
    players: pl.Int64 = pa.Field(ge=0, nullable=True)
    gxe_top: pl.Int64 = pa.Field(ge=0, le=100, nullable=True)
    gxe_p99: pl.Int64 = pa.Field(ge=0, le=100, nullable=True)
    gxe_p95: pl.Int64 = pa.Field(ge=0, le=100, nullable=True)

    class Config:
        unique = POKEMON


class Abilities(PerPokemon):
    ability: str
    weight: pl.Float32 = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "ability"]


class Items(PerPokemon):
    item: str
    weight: pl.Float32 = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "item"]


class Moves(PerPokemon):
    # "" is an empty move slot.
    move: str
    weight: pl.Float32 = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "move"]


class TeraTypes(PerPokemon):
    tera_type: str
    weight: pl.Float32 = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "tera_type"]


class Happiness(PerPokemon):
    # No bounds and no unique key: see normalize.happiness.
    happiness: float = pa.Field(nullable=True)
    weight: pl.Float32 = pa.Field(ge=0)


class Spreads(PerPokemon):
    nature: str = pa.Field(isin=NATURES)
    hp_ev: pl.Int32 = pa.Field(ge=0, le=255)
    atk_ev: pl.Int32 = pa.Field(ge=0, le=255)
    def_ev: pl.Int32 = pa.Field(ge=0, le=255)
    spa_ev: pl.Int32 = pa.Field(ge=0, le=255)
    spd_ev: pl.Int32 = pa.Field(ge=0, le=255)
    spe_ev: pl.Int32 = pa.Field(ge=0, le=255)
    weight: pl.Float32 = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "nature", "hp_ev", "atk_ev", "def_ev", "spa_ev", "spd_ev", "spe_ev"]


class Teammates(PerPokemon):
    teammate_id: str = pa.Field(nullable=True)
    association_score: pl.Float32 = pa.Field(nullable=True)
    count: pl.Float32 = pa.Field(ge=0, nullable=True)

    class Config:
        unique = [*POKEMON, "teammate_id"]


class ChecksCounters(PerPokemon):
    opponent_id: str
    n: float = pa.Field(ge=0)
    p: float = pa.Field(ge=0, le=1)
    d: float = pa.Field(ge=0)

    class Config:
        unique = [*POKEMON, "opponent_id"]


class MetagameStyles(PerCutoff):
    style: str
    pct: float = pa.Field(ge=0, le=100, nullable=True)

    class Config:
        unique = [*KEYS, "style"]


class Stalliness(PerCutoff):
    bin: float
    hashes: pl.Int32 = pa.Field(ge=0)

    class Config:
        unique = [*KEYS, "bin"]


class Mega(PerPokemon):
    pct: float = pa.Field(ge=0, le=600, nullable=True)

    class Config:
        unique = POKEMON


class MonotypeMatchups(PerCutoff):
    type: str
    opponent: str
    battles: float = pa.Field(ge=0, nullable=True)
    win_pct: float = pa.Field(ge=0, le=100, nullable=True)

    class Config:
        unique = [*KEYS, "type", "opponent"]


class MonotypeTypeRanking(PerCutoff):
    type: str
    viability_score: float = pa.Field(ge=0, nullable=True)

    class Config:
        unique = [*KEYS, "type"]


class Pokemon(pa.DataFrameModel):
    pokemon_id: str = pa.Field(unique=True)
    name: str = pa.Field(unique=True)
    num: pl.Int32
    base_species: str
    forme: str = pa.Field(nullable=True)
    gen: pl.Int32 = pa.Field(ge=1, le=9, nullable=True)
    type1: str = pa.Field(isin=TYPES)
    type2: str = pa.Field(isin=TYPES, nullable=True)
    hp: pl.Int32 = pa.Field(ge=1, le=255)
    atk: pl.Int32 = pa.Field(ge=0, le=255)
    # "def" is a Python keyword, so the column cannot be declared under its own name.
    defense: pl.Int32 = pa.Field(alias="def", ge=0, le=255)
    spa: pl.Int32 = pa.Field(ge=0, le=255)
    spd: pl.Int32 = pa.Field(ge=0, le=255)
    spe: pl.Int32 = pa.Field(ge=0, le=255)
    bst: pl.Int32 = pa.Field(ge=0)
    height_m: float = pa.Field(ge=0)
    weight_kg: float = pa.Field(ge=0)
    is_cap: bool

    class Config:
        strict = True


class Formats(pa.DataFrameModel):
    month: str
    format: str
    format_id: str
    gen: pl.Int32 = pa.Field(ge=1, le=9)
    family: str
    battles: pl.Int64 = pa.Field(ge=0, nullable=True)
    standard_cutoff: pl.Int32 = pa.Field(isin=[1630, 1695])
    is_special_month: bool
    lite_series: str = pa.Field(nullable=True)

    class Config:
        strict = True
        unique = ["month", "format"]


SCHEMAS: dict[str, type[pa.DataFrameModel]] = {
    "cutoffs": Cutoffs,
    "usage": Usage,
    "leads": Leads,
    "movesets": Movesets,
    "abilities": Abilities,
    "items": Items,
    "moves": Moves,
    "tera_types": TeraTypes,
    "happiness": Happiness,
    "spreads": Spreads,
    "teammates": Teammates,
    "checks_counters": ChecksCounters,
    "metagame_styles": MetagameStyles,
    "stalliness": Stalliness,
    "mega": Mega,
    "monotype_matchups": MonotypeMatchups,
    "monotype_type_ranking": MonotypeTypeRanking,
}

# Per file, the usage of a full team of six adds up to 600%, and one lead per team to 100%.
MAX_PCT_SUM = {"usage": 600, "leads": 100}


def check_table(name: str, table: pl.DataFrame, pokemon_ids: pl.Series, formats: pl.Series) -> None:
    """Raise ValidationError if `table` breaks a rule of the Complete table called `name`.

    `table` can be a slice of the whole table: the big ones are checked batch by batch, so
    their unique key only catches duplicates that sit in the same batch.
    `formats` holds the format names of the table's month.
    """
    problems = _schema_problems(SCHEMAS[name], table)

    unknown_formats = table.filter(~pl.col("format").is_in(formats.implode()))["format"].unique()
    if len(unknown_formats):
        problems.append(f"formats missing from the formats table: {sorted(unknown_formats)}")
    for column in set(ID_COLUMNS) & set(table.columns):
        # A null teammate is the empty slot of a team of fewer than six.
        ids = table[column].drop_nulls().unique()
        unknown_ids = ids.filter(~ids.is_in(pokemon_ids.implode()))
        if len(unknown_ids):
            problems.append(f"{column} missing from the pokemon table: {sorted(unknown_ids)}")

    if name in MAX_PCT_SUM:
        too_high = (
            table.group_by(KEYS)
            .agg(pl.col("usage_pct").sum())
            .filter(pl.col("usage_pct") > MAX_PCT_SUM[name] + ROUNDING)
        )
        if too_high.height:
            problems.append(f"usage_pct adds up to more than {MAX_PCT_SUM[name]}% in {too_high.rows()[:5]}")
    if name == "teammates":
        both_or_neither = table.filter(pl.col("association_score").is_null() == pl.col("count").is_null())
        if both_or_neither.height:
            problems.append(f"{both_or_neither.height} rows without exactly one of association_score and count")

    if problems:
        month = table["month"][0] if table.height else "?"
        raise ValidationError(f"{month}/{name}: " + "; ".join(problems))


def check_pokemon(pokemon: pl.DataFrame) -> None:
    problems = _schema_problems(Pokemon, pokemon)
    if problems:
        raise ValidationError("pokemon: " + "; ".join(problems))


def check_formats(formats: pl.DataFrame) -> None:
    problems = _schema_problems(Formats, formats)
    in_lite = formats.filter(pl.col("lite_series").is_not_null())
    doubled = in_lite.filter(pl.struct("month", "lite_series").is_duplicated())
    if doubled.height:
        problems.append(
            f"two formats in one Lite series the same month: {doubled.select('month', 'format').rows()[:5]}"
        )
    if problems:
        raise ValidationError("formats: " + "; ".join(problems))


def _schema_problems(schema: type[pa.DataFrameModel], table: pl.DataFrame) -> list[str]:
    try:
        schema.validate(table, lazy=True)
    except pandera.errors.SchemaErrors as errors:
        # pandera's own message is a JSON dump of every failing row: keep one line per broken rule.
        failures = errors.failure_cases.group_by("column", "check").agg(
            pl.len().alias("rows"), pl.col("failure_case").cast(pl.String).str.slice(0, 60).head(3).alias("examples")
        )
        return [
            f"{row['column']} fails {row['check']} ({row['rows']} rows, e.g. {row['examples']})"
            for row in failures.sort("column", "check").iter_rows(named=True)
        ]
    return []
