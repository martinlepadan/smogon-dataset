import gzip
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
from polars._typing import PolarsDataType

# Every dict[name, weight] section of a Pokémon ends up in chaos_weights under these names.
WEIGHT_SECTIONS = {
    "Abilities": "abilities",
    "Items": "items",
    "Moves": "moves",
    "Spreads": "spreads",
    "Tera Types": "tera_types",
    "Happiness": "happiness",
    "Teammates": "teammates",
}
SCALAR_KEYS = {"Raw count", "usage", "Viability Ceiling", "Checks and Counters"}

KEYS: dict[str, PolarsDataType] = {"month": pl.String, "format": pl.String, "cutoff": pl.Int32}
INFO_SCHEMA = KEYS | {
    "metagame": pl.String,
    "team_type": pl.String,
    "battles": pl.Int64,
    "cutoff_deviation": pl.Float64,
    "sections": pl.List(pl.String),
}
POKEMON_SCHEMA = KEYS | {
    "pokemon": pl.String,
    "raw_count": pl.Int64,
    "usage": pl.Float64,
    "viability_ceiling": pl.List(pl.Int64),
}
# Float32 on purpose: this table is most of the archive and the weights are sums of
# probabilities, so 7 significant digits lose nothing that matters and save ~25% of disk.
WEIGHTS_SCHEMA = KEYS | {"pokemon": pl.String, "section": pl.String, "key": pl.String, "weight": pl.Float32}
CHECKS_SCHEMA = KEYS | {
    "pokemon": pl.String,
    "opponent": pl.String,
    "n": pl.Float64,
    "p": pl.Float64,
    "d": pl.Float64,
}


@dataclass(frozen=True)
class ChaosTables:
    info: pl.DataFrame
    pokemon: pl.DataFrame
    weights: pl.DataFrame
    checks: pl.DataFrame


def read_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        return json.load(f)


def parse_chaos(raw: dict[str, Any], month: str, format: str, cutoff: int) -> ChaosTables:
    keys = {"month": month, "format": format, "cutoff": cutoff}
    info = raw["info"]
    if int(info["cutoff"]) != cutoff:
        raise ValueError(f"{month}/{format}-{cutoff}: file says cutoff {info['cutoff']}")

    sections: set[str] = set()
    pokemon_rows, weight_rows, check_rows = [], [], []
    for name, stats in raw["data"].items():
        unknown = stats.keys() - WEIGHT_SECTIONS.keys() - SCALAR_KEYS
        if unknown:
            # Never drop a field silently: the raw file is deleted after parsing.
            raise ValueError(f"{month}/{format}-{cutoff}: unknown keys {sorted(unknown)} for {name}")
        sections |= stats.keys()

        pokemon_rows.append(
            keys
            | {
                "pokemon": name,
                "raw_count": stats["Raw count"],
                "usage": stats.get("usage"),
                "viability_ceiling": stats.get("Viability Ceiling"),
            }
        )
        for source, section in WEIGHT_SECTIONS.items():
            for key, weight in stats.get(source, {}).items():
                weight_rows.append(keys | {"pokemon": name, "section": section, "key": key, "weight": weight})
        for opponent, value in stats.get("Checks and Counters", {}).items():
            # [n, p, d] up to 2023, {"n", "p", "d"} after.
            n, p, d = (value["n"], value["p"], value["d"]) if isinstance(value, dict) else value
            check_rows.append(keys | {"pokemon": name, "opponent": opponent, "n": n, "p": p, "d": d})

    info_row = keys | {
        "metagame": info["metagame"],
        "team_type": info.get("team type"),
        "battles": info["number of battles"],
        "cutoff_deviation": info["cutoff deviation"],
        "sections": sorted(sections),
    }
    return ChaosTables(
        info=pl.DataFrame([info_row], schema=INFO_SCHEMA),
        pokemon=pl.DataFrame(pokemon_rows, schema=POKEMON_SCHEMA),
        weights=pl.DataFrame(weight_rows, schema=WEIGHTS_SCHEMA),
        checks=pl.DataFrame(check_rows, schema=CHECKS_SCHEMA),
    )


def rebuild_chaos(tables: ChaosTables) -> dict[str, Any]:
    """Turn the tables back into the raw JSON, to prove parse_chaos lost nothing.

    Checks and counters come back as {"n", "p", "d"} dicts whatever the original shape and
    weights come back rounded to Float32, so compare the result with `canonical_raw(original)`.
    """
    info = tables.info.row(0, named=True)
    data: dict[str, dict[str, Any]] = {}
    for row in tables.pokemon.iter_rows(named=True):
        stats: dict[str, Any] = {"Raw count": row["raw_count"]}
        # Presence comes from `sections`, not from the value: a file where every weight is 0
        # writes "usage": null rather than leaving the key out.
        if "usage" in info["sections"]:
            stats["usage"] = row["usage"]
        if "Viability Ceiling" in info["sections"]:
            stats["Viability Ceiling"] = row["viability_ceiling"]
        data[row["pokemon"]] = stats

    sources = {section: source for source, section in WEIGHT_SECTIONS.items()}
    for source in WEIGHT_SECTIONS.keys() & set(info["sections"]):
        for stats in data.values():
            stats[source] = {}
    for pokemon, section, key, weight in tables.weights.select("pokemon", "section", "key", "weight").iter_rows():
        data[pokemon][sources[section]][key] = weight

    if "Checks and Counters" in info["sections"]:
        for stats in data.values():
            stats["Checks and Counters"] = {}
    for pokemon, opponent, n, p, d in tables.checks.select("pokemon", "opponent", "n", "p", "d").iter_rows():
        data[pokemon]["Checks and Counters"][opponent] = {"n": n, "p": p, "d": d}

    raw_info: dict[str, Any] = {
        "metagame": info["metagame"],
        "cutoff": info["cutoff"],
        "cutoff deviation": info["cutoff_deviation"],
        "number of battles": info["battles"],
    }
    if info["team_type"] is not None:
        raw_info["team type"] = info["team_type"]
    return {"info": raw_info, "data": data}


def _as_float32(value: float) -> float:
    return float(struct.unpack("f", struct.pack("f", value))[0])


def canonical_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """The raw JSON as rebuild_chaos gives it back: checks as dicts, no null team type,
    weights rounded to Float32."""
    data = {}
    for name, stats in raw["data"].items():
        data[name] = dict(stats)
        for source in WEIGHT_SECTIONS.keys() & stats.keys():
            data[name][source] = {key: _as_float32(weight) for key, weight in stats[source].items()}
        if "Checks and Counters" in stats:
            data[name]["Checks and Counters"] = {
                opponent: v if isinstance(v, dict) else dict(zip("npd", v, strict=True))
                for opponent, v in stats["Checks and Counters"].items()
            }
    info = {k: v for k, v in raw["info"].items() if not (k == "team type" and v is None)}
    return {"info": info, "data": data}
