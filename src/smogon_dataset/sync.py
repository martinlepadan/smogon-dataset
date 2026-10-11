"""Turn one month of the archive into canonical Parquet tables, then drop its raw files."""

import gzip
import shutil
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from smogon_dataset.config import INTERIM_DIR
from smogon_dataset.fetch import SmogonClient
from smogon_dataset.parsers.chaos import canonical_raw, parse_chaos, read_json, rebuild_chaos
from smogon_dataset.parsers.text import parse_leads, parse_matchups, parse_mega, parse_metagame, parse_usage

# Sorting puts repeated names next to each other, so the big tables compress better.
# Files arrive by section then (format, cutoff), so sorting each buffer keeps the file mostly ordered.
SORT_KEYS = {
    "chaos_weights": ["format", "cutoff", "pokemon", "section", "key"],
    "chaos_checks": ["format", "cutoff", "pokemon", "opponent"],
}


class MonthFailedError(Exception):
    def __init__(self, month: str, errors: list[str]) -> None:
        super().__init__(f"{month}: {len(errors)} file(s) failed to parse")
        self.month = month
        self.errors = errors


def is_synced(month: str, out_dir: Path = INTERIM_DIR) -> bool:
    return (out_dir / month).exists()


def month_files(inventory: pl.DataFrame, month: str) -> pl.DataFrame:
    """Files of a month that get parsed: everything but moveset/, which duplicates chaos/."""
    files = inventory.filter(pl.col("month") == month, ~pl.col("section").str.ends_with("moveset"))
    if files.is_empty():
        raise ValueError(f"{month} is not in the inventory")
    return files


def sync_month(
    client: SmogonClient,
    files: pl.DataFrame,
    *,
    keep_raw: bool = False,
    out_dir: Path = INTERIM_DIR,
    on_file: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Parse the files of one month (see month_files) and write data/interim/<month>/<table>.parquet.

    Every file is parsed even after a failure, so one run reports all the problems of the
    month at once. Nothing is written unless every file parses: the month then raises
    MonthFailedError, its errors go to <out_dir>/<month>.errors.txt and its raw files stay
    cached. Raw files are only deleted once the tables are on disk.
    `on_file` is called after each file, for progress reporting.
    Returns the row count of each table.
    """
    month = files["month"][0]

    # Written to <month>.part then renamed: a <month> folder always holds a complete month.
    tmp = out_dir / f"{month}.part"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    writer = MonthWriter(tmp)
    fetched: list[Path] = []
    errors: list[str] = []
    for row in files.iter_rows(named=True):
        remote = f"{month}/{row['section']}/{row['file']}" if row["section"] else f"{month}/{row['file']}"
        cached = client.fetch(remote)
        fetched.append(cached)
        try:
            parsed = parse_file(cached, row)
        except Exception as exc:
            errors.append(f"{remote}: {type(exc).__name__}: {exc}")
            if on_file:
                on_file()
            continue
        for name, df in parsed.items():
            writer.add(name, df)
        if on_file:
            on_file()
    counts = writer.close()

    error_log = out_dir / f"{month}.errors.txt"
    if errors:
        shutil.rmtree(tmp)
        error_log.write_text("\n".join(errors) + "\n")
        raise MonthFailedError(month, errors)
    error_log.unlink(missing_ok=True)
    shutil.rmtree(out_dir / month, ignore_errors=True)
    tmp.rename(out_dir / month)

    if not keep_raw:
        for path in fetched:
            path.unlink()
    return counts


class MonthWriter:
    """Appends each table to its own Parquet file as the month is parsed.

    A whole month does not fit in memory (2016-07 needs more than 8 GB), so rows are
    buffered per table and flushed as one row group every BUFFER_ROWS rows.
    """

    BUFFER_ROWS = 2_000_000

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.buffers: dict[str, list[pl.DataFrame]] = defaultdict(list)
        self.writers: dict[str, pq.ParquetWriter] = {}
        self.counts: dict[str, int] = defaultdict(int)

    def add(self, name: str, df: pl.DataFrame) -> None:
        self.buffers[name].append(df)
        if sum(part.height for part in self.buffers[name]) >= self.BUFFER_ROWS:
            self._flush(name)

    def close(self) -> dict[str, int]:
        for name in list(self.buffers):
            self._flush(name)
        for writer in self.writers.values():
            writer.close()
        return dict(self.counts)

    def _flush(self, name: str) -> None:
        df = pl.concat(self.buffers.pop(name))
        if name in SORT_KEYS:
            df = df.sort(SORT_KEYS[name])
        table = df.to_arrow()
        if name not in self.writers:
            self.writers[name] = pq.ParquetWriter(
                self.folder / f"{name}.parquet", table.schema, compression="zstd", compression_level=10
            )
        self.writers[name].write_table(table)
        self.counts[name] += df.height


def parse_file(path: Path, row: dict[str, Any]) -> dict[str, pl.DataFrame]:
    """Parse one cached file described by its inventory row."""
    month, format, cutoff, section = row["month"], row["format"], row["cutoff"], row["section"]
    keys = [
        pl.lit(month).alias("month"),
        pl.lit(format).alias("format"),
        pl.lit(cutoff, pl.Int32).alias("cutoff"),
    ]
    kind = section.rsplit("/", 1)[-1]

    # 2016-10 has a few chaos JSON files sitting at the root of the month.
    if row["ext"] == "json":
        raw = read_json(path)
        chaos = parse_chaos(raw, month, format, cutoff)
        if rebuild_chaos(chaos) != canonical_raw(raw):
            raise ValueError("rebuilding the JSON from the tables does not give the original back")
        return {
            "chaos_info": chaos.info,
            "chaos_pokemon": chaos.pokemon,
            "chaos_weights": chaos.weights,
            "chaos_checks": chaos.checks,
        }

    text = read_text(path)
    if kind == "leads":
        return {"leads": parse_leads(text).select(*keys, pl.all())}
    if kind == "metagame":
        styles, stalliness = parse_metagame(text)
        return {
            "metagame": styles.select(*keys, pl.all()),
            "metagame_stalliness": stalliness.select(*keys, pl.all()),
        }
    if kind == "mega":
        return {"mega": parse_mega(text).select(*keys, pl.all())}
    if kind == "matchupcharts":
        matrix, ranking = parse_matchups(text)
        return {
            "monotype_matchups": matrix.select(*keys, pl.all()),
            "monotype_type_ranking": ranking.select(*keys, pl.all()),
        }
    if kind in ("", "monotype"):
        # 2016-10: the cap usage files were overwritten with moveset reports, which only
        # repeat the chaos JSON sitting next to them.
        is_moveset_report = "Total battles" not in text and "Raw count" in text
        return {} if is_moveset_report else {"usage": parse_usage(text).select(*keys, pl.all())}
    raise ValueError(f"no parser for section {section!r}")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    return (gzip.decompress(data) if path.suffix == ".gz" else data).decode()
