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
pokemon = ss.load("pokemon")
lite_usage = ss.load_lite("usage")
```

`load` reads the Complete dataset. Give it `years` or `months`, not both; with neither it takes everything since 2014, which means a lot of files for the big tables. `formats` and `cutoffs` are filters applied lazily, so nothing is read until you call `.collect()`.

Months are strings like `2024-01`. A few months were published by Smogon in several parts and carry a suffix, e.g. `2020-11-H1` or `2023-09-DLC1`.

`pokemon` and `formats` are the two tables shared by every year: `formats` comes back for the years you asked, `pokemon` from the most recent of them.

`load_lite` reads the Lite dataset: the most played formats at their standard cutoff, one file per table.

If you already have the datasets on disk, set `SMOGON_STATS_DIR` to the folder that holds `lite/`, `complete-2024/` and so on, and nothing is downloaded.

## Data

- Lite: <https://www.kaggle.com/datasets/martinlepadan/smogon-usage-stats-lite>
- Complete: <https://www.kaggle.com/datasets/martinlepadan/smogon-usage-stats-complete-2014> and so on, one per year

The numbers come from the monthly reports at <https://www.smogon.com/stats/>, starting in November 2014. The tables and their columns are described on the Kaggle pages.
