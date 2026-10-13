# smogon-stats

Reads the [Smogon usage statistics](https://www.smogon.com/stats/) datasets published on Kaggle and hands them back as [polars](https://pola.rs) LazyFrames.

The Complete dataset is split into one Kaggle dataset per year, with one parquet file per table and per month. This package fetches only the files a query needs, keeps them in the `kagglehub` cache, and stitches them into a single table. No Kaggle account is required.

## Install

```
pip install smogon-stats
```

## Usage

```python
import smogon_stats as ss

usage = ss.load("usage", years=range(2020, 2027))
moves = ss.load("moves", months=["2024-01", "2024-02"], formats=["gen9ou"])
little_cup = ss.load("usage", years=range(2015, 2021), family="lc", cutoffs="standard")
pokemon = ss.load("pokemon")
lite_usage = ss.load_lite("usage", years=[2024])
```

`load` reads the Complete dataset. Give it `years` or `months`, not both; with neither it takes everything since 2014, which means a lot of files for the big tables. The other arguments are filters, and they all narrow the result. Nothing is read until you call `.collect()`.

| Argument | Keeps |
|---|---|
| `formats=["gen9ou"]` | formats by the name Smogon gave them that month |
| `family="lc"` | a tier under every name it had (`lc`, `gen7lc`, `gen8lc`...), all generations |
| `cutoffs=[0, 1500]` | those rating cutoffs |
| `cutoffs="standard"` | the standard cutoff of each format: 1695 for the OU and Doubles OU of the current generation, 1630 for the rest |

`family` and `cutoffs="standard"` are looked up in the `formats` table of the years asked. A family holds one format per generation, so a month of `family="lc"` has the Little Cup of the day and the ladders of older generations: filter on `formats.gen` or `formats.battles` to keep one. With both `family` and `formats`, a format must match both.

Months are strings like `2024-01`. A few months were also published by Smogon in parts, which carry a suffix: `2020-11-H1`, `2023-09-DLC1`. They repeat battles of the whole month, so `load` leaves them out. Name them in `months` to get them, or pass `include_special_months=True` to get them along with the `years` asked.

Three tables are not split by month:

- `ss.load("formats")` has one row per month and format, for the years asked or all of them. It is small: 13 files for 11,000 rows.
- `ss.load("pokemon")` is the pokedex. Every year ships a full one, so it comes from the most recent year asked, or from the latest year when none is given.
- `ss.load("files")` lists the tables and months each year holds, special months included.

`load_lite` reads the Lite dataset: the most played formats at their standard cutoff, one file per table and no special months. It takes `years`, `months` and `formats`.

## Changes in 0.2.0

- `load` no longer returns the special months unless asked: `ss.load("usage", years=[2020])` has 12 months where 0.1 gave 18. Pass `include_special_months=True` for the old behaviour.
- New in `load`: `family=`, `cutoffs="standard"`, `include_special_months=`.
- New in `load_lite`: `years=` and `months=`.

If you already have the datasets on disk, set `SMOGON_STATS_DIR` to the folder that holds `lite/`, `complete-2024/` and so on, and nothing is downloaded.

## Data

- Lite: <https://www.kaggle.com/datasets/martinlepadan/smogon-usage-stats-lite>
- Complete: <https://www.kaggle.com/datasets/martinlepadan/smogon-usage-stats-complete-2014> and so on, one per year

The numbers come from the monthly reports at <https://www.smogon.com/stats/>, starting in November 2014. The tables and their columns are described on the Kaggle pages.
