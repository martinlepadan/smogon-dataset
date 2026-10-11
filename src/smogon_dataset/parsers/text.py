"""Parsers for the plain-text files: usage (root), leads, metagame, mega and matchup charts.

The raw files are deleted once parsed, so every parser accounts for every line: a line that
matches no known pattern raises instead of being skipped.
"""

import re
from collections.abc import Callable

import polars as pl

# Until 2023 every line starts with a space, so all patterns allow leading whitespace.
_BORDER = re.compile(r"^\s*\+[-+ ]+\+\s*$")
_HEADER_ROW = re.compile(r"^\s*\|\s*Rank\s*\|")
# Smogon prints NaN when every team weighs 0 (e.g. a single battle at a high cutoff).
_NUMBER = r"(?:[-+]?\d+(?:\.\d+)?|NaN)"


class UnparsedLineError(ValueError):
    pass


def _num(value: str) -> float | None:
    """'12.5%' or '12.5' -> 12.5. NaN becomes null, as in the chaos files where Smogon writes null."""
    value = value.strip().rstrip("%")
    return None if value == "NaN" else float(value)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _consume(text: str, handlers: list[tuple[re.Pattern[str], Callable[[re.Match[str]], None]]]) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for pattern, handle in handlers:
            match = pattern.match(line)
            if match:
                handle(match)
                break
        else:
            raise UnparsedLineError(f"line {number}: {line!r}")


def _skip(_: re.Match[str]) -> None:
    pass


def parse_usage(text: str) -> pl.DataFrame:
    header: dict[str, float | None] = {}
    rows: list[dict[str, object]] = []

    def row(m: re.Match[str]) -> None:
        rank, pokemon, usage, raw, raw_pct, real, real_pct = _table_cells(m.string)
        rows.append(
            {
                "rank": int(rank),
                "pokemon": pokemon,
                "usage_pct": _num(usage),
                "raw": int(raw),
                "raw_pct": _num(raw_pct),
                "real": int(real),
                "real_pct": _num(real_pct),
            }
        )

    _consume(
        text,
        [
            (re.compile(r"^\s*Total battles:\s*(\d+)"), lambda m: header.update(battles=int(m[1]))),
            (re.compile(rf"^\s*Avg\. weight/team:\s*({_NUMBER})"), lambda m: header.update(avg_weight=_num(m[1]))),
            (_BORDER, _skip),
            (_HEADER_ROW, _skip),
            (re.compile(r"^\s*\|\s*\d+\s*\|"), row),
        ],
    )
    return pl.DataFrame(
        rows,
        schema={
            "rank": pl.Int32,
            "pokemon": pl.String,
            "usage_pct": pl.Float64,
            "raw": pl.Int64,
            "raw_pct": pl.Float64,
            "real": pl.Int64,
            "real_pct": pl.Float64,
        },
        # .get: Smogon serves a few empty files (2015-03 randombattle-1695), which give an empty table.
    ).with_columns(
        battles=pl.lit(header.get("battles"), pl.Int64), avg_weight=pl.lit(header.get("avg_weight"), pl.Float64)
    )


def parse_leads(text: str) -> pl.DataFrame:
    header: dict[str, int] = {}
    rows: list[dict[str, object]] = []

    def row(m: re.Match[str]) -> None:
        rank, pokemon, usage, raw, raw_pct = _table_cells(m.string)
        rows.append(
            {
                "rank": int(rank),
                "pokemon": pokemon,
                "usage_pct": _num(usage),
                "raw": int(raw),
                "raw_pct": _num(raw_pct),
            }
        )

    _consume(
        text,
        [
            (re.compile(r"^\s*Total leads:\s*(\d+)"), lambda m: header.update(total_leads=int(m[1]))),
            (_BORDER, _skip),
            (_HEADER_ROW, _skip),
            (re.compile(r"^\s*\|\s*\d+\s*\|"), row),
        ],
    )
    return pl.DataFrame(
        rows,
        schema={
            "rank": pl.Int32,
            "pokemon": pl.String,
            "usage_pct": pl.Float64,
            "raw": pl.Int64,
            "raw_pct": pl.Float64,
        },
    ).with_columns(total_leads=pl.lit(header.get("total_leads"), pl.Int64))


def parse_metagame(text: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Team styles, then the stalliness histogram printed under them."""
    styles: list[dict[str, object]] = []
    labels: list[float | None] = []
    hashes: list[int] = []
    stalliness: dict[str, float | None] = {}

    def histogram_row(m: re.Match[str]) -> None:
        labels.append(float(m[1]) if m[1] else None)
        hashes.append(len(m[2]))

    _consume(
        text,
        [
            (
                re.compile(rf"^\s*(\S+?)\.+\s*({_NUMBER})%$"),
                lambda m: styles.append({"style": m[1], "pct": _num(m[2])}),
            ),
            (re.compile(rf"^\s*Stalliness \(mean:\s*({_NUMBER})\)"), lambda m: stalliness.update(mean=_num(m[1]))),
            (re.compile(rf"^\s*({_NUMBER})?\s*\|(#*)\s*$"), histogram_row),
            (re.compile(r"^\s*more negative = more offensive"), _skip),
            (re.compile(rf"^\s*one # =\s*({_NUMBER})%"), lambda m: stalliness.update(pct_per_hash=_num(m[1]))),
        ],
    )
    style_df = pl.DataFrame(styles, schema={"style": pl.String, "pct": pl.Float64})
    bins_df = pl.DataFrame(
        {"bin": _histogram_bins(labels), "hashes": hashes}, schema={"bin": pl.Float64, "hashes": pl.Int32}
    ).with_columns(
        mean=pl.lit(stalliness.get("mean"), pl.Float64),
        pct_per_hash=pl.lit(stalliness.get("pct_per_hash"), pl.Float64),
    )
    return style_df, bins_df


def _histogram_bins(labels: list[float | None]) -> list[float]:
    """Fill in the unlabelled rows of the histogram.

    Only every other row has a label, and the step changes between files (labels 0.5 or
    1.0 apart), so it is read off the first two labels.
    """
    if not labels:
        return []
    (i, first), (j, second) = [(k, label) for k, label in enumerate(labels) if label is not None][:2]
    step = (second - first) / (j - i)
    return [first + (k - i) * step for k in range(len(labels))]


def parse_mega(text: str) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    _consume(
        text,
        [
            (
                re.compile(rf"^\s*(.+?)\s+({_NUMBER})%$"),
                lambda m: rows.append({"pokemon": m[1], "pct": _num(m[2])}),
            )
        ],
    )
    return pl.DataFrame(rows, schema={"pokemon": pl.String, "pct": pl.Float64})


def parse_matchups(text: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    """The type-vs-type matrix (battles on one line, win rate on the next), then the type ranking."""
    columns: list[str] = []
    cells: list[dict[str, object]] = []
    ranking: list[dict[str, object]] = []

    def matrix_row(m: re.Match[str]) -> None:
        first, *values = _table_cells(m.string)
        if not columns:
            columns.extend(values)
        elif first:
            cells.extend(
                {"type": first, "opponent": c, "battles": _num(v)} for c, v in zip(columns, values, strict=True)
            )
        else:
            for cell, v in zip(cells[-len(columns) :], values, strict=True):
                cell["win_pct"] = _num(v)

    _consume(
        text,
        [
            (re.compile(r"^Matchup Chart and Type Ranking"), _skip),
            (re.compile(r"^\+[-+]+\+$"), _skip),
            (re.compile(r"^\|.*\|$"), matrix_row),
            (re.compile(r"^Type\.+ViabilityScore$"), _skip),
            (
                re.compile(rf"^(\w+)\.+({_NUMBER})$"),
                lambda m: ranking.append({"type": m[1], "viability_score": _num(m[2])}),
            ),
        ],
    )
    matrix = pl.DataFrame(
        cells, schema={"type": pl.String, "opponent": pl.String, "battles": pl.Float64, "win_pct": pl.Float64}
    )
    return matrix, pl.DataFrame(ranking, schema={"type": pl.String, "viability_score": pl.Float64})
