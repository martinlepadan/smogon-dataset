"""The Kaggle cards: what goes into dataset-metadata.json for the Lite dataset and for each Complete year."""

from collections.abc import Mapping

import polars as pl

from smogon_dataset.columns import COLUMNS, KEYS, TABLES, lite_columns

OWNER = "martinlepadan"
# Not decided yet. "other" is Kaggle's "see the description".
LICENSE = "CC-BY-4.0"
SOURCES = (
    "Monthly usage statistics published by Smogon at https://www.smogon.com/stats/, computed from Pokémon Showdown "
    "battles. Pokémon data from https://github.com/smogon/pokemon-showdown."
)
# Kaggle drops without a word the keywords that are not tags it knows.
KEYWORDS = ["games", "video games", "tabular"]

LITE_SLUG = "smogon-usage-stats-lite"
# Files at the root of a Complete year. The CLI matches `resources[].path` against the names it
# uploads, and a table folder goes up as one archive: only these can carry column descriptions.
ROOT_TABLES = ("pokemon", "formats", "files")

Schemas = Mapping[str, Mapping[str, pl.DataType]]

_SOURCE = """\
All the numbers come from [smogon.com/stats](https://www.smogon.com/stats/). Smogon computes them every month \
from the battles played on [Pokémon Showdown](https://pokemonshowdown.com/) and publishes them as text and JSON \
files, one set per format and rating cutoff. This dataset reshapes those files into tables. The `pokemon` table \
comes from the Pokémon Showdown pokedex.

This is an independent project, not affiliated with Smogon or Pokémon Showdown.

The reshaping done here is released under CC BY 4.0: use it however you like, as long as you credit this \
dataset and its author. The statistics themselves are published by Smogon, so please credit smogon.com/stats too."""

_KEYS = """\
Every table of statistics has `month`, `format` and `cutoff`, and those about Pokémon also have `pokemon_id`: \
join them on those. `formats` joins on `month` and `format`, `pokemon` on `pokemon_id`.

""" + "\n".join(f"- `{column}`: {text}" for column, text in KEYS.items())

_QUIRKS = """\
- The statistics are weighted: a battle counts for the probability that the player is rated above the cutoff. \
At cutoff 0 every battle counts the same.
- `usage_pct` adds up to about 600 per file, since a team has six Pokémon. It goes above 100 (up to 118) in the \
formats where a team can field the same species several times.
- Generation 6 formats have no prefix until 2017-06: `ou` is the OU of generation 6. `formats.format_id` spells \
the generation out and `formats.family` drops it.
- The details of a Pokémon (abilities, items, moves...) come from Smogon's `chaos` files, which leave out the \
Pokémon with negligible usage. About half the rows of `usage` have no match in those tables.
- An empty string in `move` is an empty move slot. `nothing` in `item` or `tera_type` means no item, no Tera type.
- Tera types are only published from 2024-08.
- Ids follow today's Pokémon Showdown: the few Pokémon renamed since the old files carry their current id."""

_LITE = """\
Monthly usage statistics of competitive Pokémon since November 2014: how often each Pokémon is used in a format, \
and with which abilities, items, moves and Tera types.

This is the small version, made to be opened as it is: the most played formats, one rating cutoff, one file per \
table, in CSV and in Parquet. The rest is in the Complete datasets, linked at the bottom.

## Source

{source}

## What is in it

- **Formats**: the OU tier of every generation (`gen1ou` to `gen9ou`), eight tiers followed from one generation \
to the next (Ubers, UU, RU, NU, Doubles OU, National Dex, Monotype, Anything Goes) and the most played VGC format \
of each month. `formats.lite_series` says which series a row belongs to.
- **Cutoff**: one per format and month, the standard one: 1695 where Smogon publishes it, 1630 otherwise.
- **Months**: whole months only. The DLC and half-month folders of the archive are left out: they are slices of \
months that are also published whole.
- **Files**: every table comes as `<table>.parquet` and `<table>.csv`, with the same content.
- In `abilities`, `items`, `moves` and `tera_types`, `pct` is the share of the Pokémon's sets in %, and the rows \
under 0.1 % are dropped.

## Keys

{keys}

## Things to know

{quirks}
- The share of the empty move slot can go above 100 %, up to 300 % for a Pokémon with a single move.
- Smogon's usage file of Anything Goes for 2016-02 is empty: that month the series has abilities, items and \
moves but no usage ranking.

## The Complete datasets

Every format (several hundred), every cutoff, the raw weights behind the percentages, and the tables left out \
here, such as leads, spreads, teammates, checks and counters or team styles. Same keys and same column names \
as the Lite. One dataset per year:

{years}
"""

_COMPLETE = """\
Monthly usage statistics of competitive Pokémon for {year}: every format, every rating cutoff and every table of \
smogon.com/stats, in Parquet.

The archive starts in November 2014. It is cut into one dataset per year, so that only the current year has to be \
sent again when a month comes out:

{years}

For the main formats in a few CSV files, see [Smogon Usage Stats Lite]({lite_url}): same keys, same column names, \
a fraction of the size.

## Source

{source}

## Files

A table is a folder with one file per month: `usage/{month}.parquet`. `files.parquet` lists the files of this \
dataset, one row per `table` and `month`. A table has no file for a month where it is empty. `pokemon.parquet` \
and `formats.parquet` sit at the root.

`kagglehub` downloads one file at a time, without a Kaggle account:

```python
import kagglehub
import polars as pl

path = kagglehub.dataset_download("{handle}", path="usage/{month}.parquet")
usage = pl.read_parquet(path)
```

## Keys

{keys}

## Things to know

{quirks}
- The tables of abilities, items, moves, Tera types, spreads and happiness hold raw weights, not percentages. \
Every set has one ability, so the sum of the ability weights of a Pokémon in a file is the weight of all its \
sets: divide by it to get the percentages Smogon prints.
- `teammates` has two measures and never both: `association_score` until 2021-03, `count` from 2021-04. Smogon \
changed what it publishes under the same name.
- Folders such as `2020-06-DLC1` or `2020-11-H1` are slices of a month that is also published whole. They are \
kept under their own `month`, flagged by `formats.is_special_month`: do not add them to the whole month.
- In 2016-12 `randombattle` and `gen6randombattle` both exist, so `format_id` is not unique that month. `format` \
always is.
- Two usage files are empty at the source: `randombattle` at 1695 in 2015-03 and `anythinggoes` at 1630 in 2016-02.
- Four formats of 2025-05 have files and 0 battles.
- In 2022-02 Smogon lists `Venomicon` under two spellings in `gen8cap` and `gen8metronomebattle`. They are merged \
here: usage and leads added up, the repeated moveset entry dropped.
- `happiness` has absurd values typed in by hackmons players, and nulls.
- `mega` only exists from 2014-11 to 2015-10. Its `pokemon_id` is the Mega or Primal forme.

## Tables

The columns of the three root files are described in the data explorer. Kaggle cannot attach column descriptions \
to files in folders, so here are the others. The key columns above are not repeated.

{tables}
"""


def complete_slug(year: str) -> str:
    return f"smogon-usage-stats-complete-{year}"


def lite_card(schemas: Schemas, years: list[str]) -> dict[str, object]:
    """`schemas` holds the columns and types of each Lite file, `years` the Complete datasets to link to."""
    return {
        # The title slugifies to the id, in case Kaggle wants the two to agree.
        "title": "Smogon Usage Stats Lite",
        "subtitle": "Competitive Pokémon usage by month since 2014: main formats, CSV and Parquet",
        "id": f"{OWNER}/{LITE_SLUG}",
        "licenses": [{"name": LICENSE}],
        "keywords": KEYWORDS,
        "userSpecifiedSources": SOURCES,
        "expectedUpdateFrequency": "monthly",
        "description": _LITE.format(source=_SOURCE, keys=_KEYS, quirks=_QUIRKS, years=_year_links(years)),
        "resources": [
            _resource(f"{table}{suffix}", table, schema, lite_columns(table))
            for table, schema in schemas.items()
            for suffix in (".parquet", ".csv")
        ],
    }


def complete_card(year: str, years: list[str], month: str, schemas: Schemas) -> dict[str, object]:
    """`schemas` holds every table the year has, `month` is one of its months, used in the examples."""
    slug = complete_slug(year)
    description = _COMPLETE.format(
        year=year,
        years=_year_links([other for other in years if other != year]),
        lite_url=_url(LITE_SLUG),
        source=_SOURCE,
        month=month,
        handle=f"{OWNER}/{slug}",
        keys=_KEYS,
        quirks=_QUIRKS,
        tables="\n\n".join(
            _table_section(table, schema) for table, schema in schemas.items() if table not in ROOT_TABLES
        ),
    )
    return {
        "title": f"Smogon Usage Stats Complete {year}",
        "subtitle": f"Every format, cutoff and table of smogon.com/stats for {year}, in Parquet",
        "id": f"{OWNER}/{slug}",
        "licenses": [{"name": LICENSE}],
        "keywords": KEYWORDS,
        "userSpecifiedSources": SOURCES,
        # A past year is never sent again.
        "expectedUpdateFrequency": "monthly" if year == max(years) else "never",
        "description": description,
        "resources": [_resource(f"{table}.parquet", table, schemas[table], COLUMNS[table]) for table in ROOT_TABLES],
    }


def _url(slug: str) -> str:
    return f"https://www.kaggle.com/datasets/{OWNER}/{slug}"


def _year_links(years: list[str]) -> str:
    return "\n".join(f"- [{year}]({_url(complete_slug(year))})" for year in years)


def _kaggle_type(dtype: pl.DataType) -> str:
    if dtype.is_integer():
        return "integer"
    if dtype.is_float():
        return "decimal"
    return "boolean" if dtype == pl.Boolean else "string"


def _resource(path: str, table: str, schema: Mapping[str, pl.DataType], described: dict[str, str]) -> dict[str, object]:
    # Kaggle pairs fields and columns by position: all of them, in the order of the file.
    fields = [
        {"name": column, "description": described[column], "type": _kaggle_type(dtype)}
        for column, dtype in schema.items()
    ]
    return {"path": path, "description": TABLES[table], "schema": {"fields": fields}}


def _table_section(table: str, schema: Mapping[str, pl.DataType]) -> str:
    columns = [
        f"- `{column}` ({_kaggle_type(dtype)}): {COLUMNS[table][column]}"
        for column, dtype in schema.items()
        if COLUMNS[table][column] != KEYS.get(column)
    ]
    return "\n".join([f"### {table}", "", TABLES[table], "", *columns])
