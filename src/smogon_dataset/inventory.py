import re
from collections.abc import Iterator
from pathlib import Path

import polars as pl

from smogon_dataset.config import INTERIM_DIR
from smogon_dataset.fetch import SmogonClient
from smogon_dataset.listing import parse_listing

# Cutoff is always the last dash-separated chunk: "gen9monotype-monobug-1630.txt" is
# format "gen9monotype-monobug" at cutoff 1630.
_STATS_FILE = re.compile(r"^(?P<format>.+)-(?P<cutoff>\d+)\.(?P<ext>txt|json)$")

INVENTORY_PATH = INTERIM_DIR / "inventory.parquet"

SCHEMA = {
    "month": pl.String,
    "section": pl.String,
    "file": pl.String,
    "format": pl.String,
    "cutoff": pl.Int32,
    "ext": pl.String,
    "size": pl.Int64,
    "modified": pl.Datetime,
}


def list_months(client: SmogonClient, refresh: bool = False) -> list[str]:
    return [e.name for e in parse_listing(client.get("", refresh=refresh).decode()) if e.is_dir]


def walk_month(client: SmogonClient, month: str, refresh: bool = False) -> Iterator[dict[str, object]]:
    """Yield one row per file in a month folder, recursing into every subfolder."""
    pending = [""]
    while pending:
        section = pending.pop()
        html = client.get(f"{month}/{section}", refresh=refresh).decode()
        for entry in parse_listing(html):
            if entry.is_dir:
                pending.append(f"{section}{entry.name}/")
                continue
            match = _STATS_FILE.match(entry.name)
            yield {
                "month": month,
                "section": section.rstrip("/"),
                "file": entry.name,
                "format": match["format"] if match else None,
                "cutoff": int(match["cutoff"]) if match else None,
                "ext": match["ext"] if match else Path(entry.name).suffix.lstrip("."),
                "size": entry.size,
                "modified": entry.modified,
            }


def build_inventory(
    client: SmogonClient, months: list[str] | None = None, previous: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Crawl `months` (default: all). The other months of `previous` are kept as they are."""
    # The latest month can still gain files, so its listings are always refetched.
    all_months = list_months(client, refresh=True)
    latest = all_months[-1]
    crawled = months or all_months
    rows = [row for month in crawled for row in walk_month(client, month, refresh=month == latest)]
    inventory = pl.DataFrame(rows, schema=SCHEMA)
    if previous is not None:
        inventory = pl.concat([previous.filter(~pl.col("month").is_in(crawled)), inventory])
    return inventory.sort("month", "section", "file")


def standard_cutoffs(inventory: pl.DataFrame) -> pl.DataFrame:
    """Lite cutoff of each (month, format): 1695 where Smogon publishes it, 1630 otherwise.

    1695 is not tied to a format name: it goes to the OU and Doubles OU of the current
    generation, and moves on when a new generation comes out (gen8ou drops to 1630 in 2022-11).
    """
    return (
        inventory.filter(pl.col("section").is_in(["", "monotype"]), pl.col("cutoff").is_in([1630, 1695]))
        .group_by("month", "format")
        .agg(pl.col("cutoff").max())
        .sort("month", "format")
    )
