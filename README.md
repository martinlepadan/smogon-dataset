# Smogon Usage Stats

ETL pipeline that turns the Pokemon Showdown usage stats archive
([smogon.com/stats](https://www.smogon.com/stats/), since November 2014) into **two Kaggle datasets**,
normalized and updated automatically every month:

- **Lite**: the most played formats, standard rating cutoff only, CSV + Parquet.
- **Complete**: every format, every cutoff, every section, partitioned Parquet.

> Status: WIP

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # venv + dev dependencies
uv sync --group notebook     # adds Jupyter and matplotlib for the notebooks
uv run pre-commit install    # git hooks (ruff, mypy, basic checks)
cp .env.example .env         # Kaggle credentials, only needed to publish
```

## Commands

```bash
uv run smogon-dataset --help        # pipeline CLI
uv run smogon-dataset inventory     # 1. list every file of the archive
uv run smogon-dataset sync          # 2. download and parse the months not done yet
uv run smogon-dataset pokemon       # 3. build the pokemon table, check every name against it
uv run smogon-dataset formats       # 4. build the formats table
uv run smogon-dataset normalize     # 5. write the Complete tables, validated on the way out
uv run pytest -m "not network"      # tests that don't hit smogon.com
uv run pytest --cov                 # with coverage
uv run ruff check --fix && uv run ruff format
uv run mypy
```

## Architecture

```
src/smogon_dataset/
  config.py        # source URL, rate limiting, paths
  cli.py           # `smogon-dataset` entry point
  fetch.py         # polite HTTP client with an on-disk cache
  listing.py       # reads the server's directory pages
  inventory.py     # crawl of the archive listings: one row per file
  parsers/         # raw file -> canonical tables, same shape for every era
  sync.py          # download + parse one month, then drop its raw files
  pokedex.py       # `pokemon` table from the Pokémon Showdown pokedex
  formats.py       # `formats` table: generation, family, Lite series
  normalize.py     # canonical tables -> tables of the Complete dataset
  validate.py      # pandera schemas and rules every Complete table must pass
scripts/           # one-off tools (fixture download)
tests/
  fixtures/<month> # real sample files from each era, laid out like the server
data/              # not versioned
  raw/             # cache of smogon.com/stats, files kept gzipped as served
  interim/         # canonical tables, one folder per month
  complete/        # Complete dataset
  lite/            # Lite dataset
notebooks/         # exploration and the Kaggle starter notebook
.github/workflows/ # CI + monthly update
```

## Source and attribution

Usage stats are published by [Smogon](https://www.smogon.com/stats/) and computed from
[Pokémon Showdown](https://pokemonshowdown.com/) battles. Pokémon data (types, base stats) comes from
[smogon/pokemon-showdown](https://github.com/smogon/pokemon-showdown).
