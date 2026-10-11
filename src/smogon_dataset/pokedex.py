"""The `pokemon` table, built from the Pokémon Showdown pokedex.

Smogon's stats are computed by Showdown, so both use the same names: lowercasing a name
from the stats and dropping everything but letters and digits gives the pokedex key.
"""

from pathlib import Path
from typing import Any

import httpx
import polars as pl

from smogon_dataset.config import INTERIM_DIR, RAW_DIR, REQUEST_TIMEOUT_S, USER_AGENT

POKEDEX_URL = "https://play.pokemonshowdown.com/data/pokedex.json"
POKEDEX_PATH = RAW_DIR / "showdown" / "pokedex.json"
POKEMON_PATH = INTERIM_DIR / "pokemon.parquet"

# Names found in old stats that Showdown has renamed since.
RENAMED = {
    "floetteeternalflower": "floetteeternal",
    "mimikyutotembusted": "mimikyubustedtotem",
    "taurospaldea": "taurospaldeacombat",
    "taurospaldeafire": "taurospaldeablaze",
    "taurospaldeawater": "taurospaldeaaqua",
    # mega/ names the species holding the stone, and tells the two stones apart this way until 2015-10.
    "charizardx": "charizardmegax",
    "charizardy": "charizardmegay",
    "mewtwox": "mewtwomegax",
    "mewtwoy": "mewtwomegay",
}

# Tables of a synced month with a Pokémon name column, and that column.
NAME_COLUMNS = {
    "usage": "pokemon",
    "leads": "pokemon",
    "mega": "pokemon",
    "chaos_pokemon": "pokemon",
    "chaos_checks": "opponent",
}

STATS = ("hp", "atk", "def", "spa", "spd", "spe")

# First national dex number of each generation, latest first.
FIRST_NUM = {9: 906, 8: 810, 7: 722, 6: 650, 5: 494, 4: 387, 3: 252, 2: 152, 1: 1}

SCHEMA = {
    "pokemon_id": pl.String,
    "name": pl.String,
    "num": pl.Int32,
    "base_species": pl.String,
    "forme": pl.String,
    "gen": pl.Int32,
    "type1": pl.String,
    "type2": pl.String,
    **{stat: pl.Int32 for stat in STATS},
    "bst": pl.Int32,
    "height_m": pl.Float64,
    "weight_kg": pl.Float64,
    "is_cap": pl.Boolean,
}


def download_pokedex(dest: Path = POKEDEX_PATH) -> Path:
    response = httpx.get(POKEDEX_URL, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest


def pokemon_id(name: pl.Expr) -> pl.Expr:
    """Pokedex key of a name as the stats spell it: 'Great Tusk' -> 'greattusk'."""
    return name.str.to_lowercase().str.replace_all("[^a-z0-9]", "").replace(RENAMED)


def build_pokemon(pokedex: dict[str, dict[str, Any]]) -> pl.DataFrame:
    keys = {species["name"]: key for key, species in pokedex.items()}
    rows = []
    for key, entry in pokedex.items():
        # Cosmetic formes (Gastrodon-East) only carry a name and a colour: the rest is the base species'.
        species = pokedex[keys[entry["baseSpecies"]]] | entry if entry.get("isCosmeticForme") else entry
        types = species["types"]
        stats = species["baseStats"]
        rows.append(
            {
                "pokemon_id": key,
                "name": species["name"],
                "num": species["num"],
                "base_species": species.get("baseSpecies", species["name"]),
                "forme": species.get("forme"),
                "gen": _generation(species),
                "type1": types[0],
                "type2": types[1] if len(types) > 1 else None,
                **{stat: stats[stat] for stat in STATS},
                "bst": sum(stats[stat] for stat in STATS),
                "height_m": species["heightm"],
                "weight_kg": species["weightkg"],
                "is_cap": species.get("isNonstandard") == "CAP",
            }
        )
    return pl.DataFrame(rows, schema=SCHEMA).sort("num", "pokemon_id")


def _generation(species: dict[str, Any]) -> int | None:
    """Generation a forme first appeared in.

    The pokedex only spells it out when it cannot be guessed, so this is Showdown's own
    rule (sim/dex-species.ts): the later of what the dex number and the forme name say.
    """
    if "gen" in species:
        return int(species["gen"])
    num = species["num"]
    # MissingNo. is number 0 and belongs to no generation.
    if num < 1:
        return None
    by_num = next(gen for gen, first in FIRST_NUM.items() if num >= first)
    return max(by_num, _forme_generation(species.get("forme", "")))


def _forme_generation(forme: str) -> int:
    """Generation of the formes added to an older species (Mega Charizard, Alolan Raichu), else 0."""
    if "Paldea" in forme:
        return 9
    if forme in ("Gmax", "Galar", "Galar-Zen", "Hisui"):
        return 8
    if forme.startswith("Alola") or forme == "Starter":
        return 7
    if "Mega" in forme or forme == "Primal":
        return 6
    return 0


def unknown_names(pokemon: pl.DataFrame, month_dir: Path) -> pl.DataFrame:
    """Names in the tables of a synced month that match no row of `pokemon`."""
    known = pokemon["pokemon_id"]
    found = [
        pl.scan_parquet(path).select(pl.col(column).alias("name")).unique()
        for table, column in NAME_COLUMNS.items()
        if (path := month_dir / f"{table}.parquet").exists()
    ]
    names = pl.concat(found).unique().collect()
    return names.filter(~pokemon_id(pl.col("name")).is_in(known.implode())).sort("name")
