"""What every table and every column of the published datasets means.

Written once here, read by the Lite card and by the Complete ones, so that both say the
same thing. tests/test_columns.py fails when a table drifts from its model in validate.py.
"""

from smogon_dataset.lite import WEIGHT_TABLES

_FILE_KEYS = {
    "month": "Month of the statistics, `YYYY-MM`. A few folders of the archive cover part of a month only "
    "(`2020-06-DLC1`, `2020-11-H1`): see `formats.is_special_month`.",
    "format": "Format name as Smogon wrote it that month (`gen9ou`, `ou`, `gen9monotype-monobug`). "
    "Generation 6 formats have no prefix until 2017-06: see `formats.format_id`.",
    "cutoff": "Rating threshold of the source file: 0, 1500, 1630, 1695, 1760 or 1825. Each battle is weighted "
    "by the probability that the player's rating is above it.",
}
KEYS = {
    **_FILE_KEYS,
    "pokemon_id": "Pokémon Showdown id of the Pokémon (`greattusk`, `rotomwash`). Joins to the `pokemon` table.",
}
_WEIGHT = (
    "Weighted number of the Pokémon's sets that have it, with the weighting of the cutoff. Divide by the sum of "
    "the Pokémon's ability weights in the same file to get the share Smogon prints."
)
_PCT = "Share of the Pokémon's sets that have it, in %. Rows under 0.1 are left out."
_EV = "EVs put in {stat}, 0 to 252 on a legal set."

TABLES = {
    "pokemon": "One row per Pokémon forme, from the Pokémon Showdown pokedex: types and base stats.",
    "formats": "One row per format and month: what the format name stands for, and how many battles it had.",
    "files": "One row per data file of this dataset: the file is `<table>/<month>.parquet`.",
    "cutoffs": "One row per format, month and cutoff: the figures Smogon gives once per file.",
    "usage": "One row per Pokémon, format, month and cutoff: the usage ranking.",
    "leads": "One row per Pokémon, format, month and cutoff: how often it is sent out first.",
    "movesets": "One row per Pokémon listed in a moveset file: raw count and how good its users are.",
    "abilities": "One row per Pokémon and ability.",
    "items": "One row per Pokémon and held item.",
    "moves": "One row per Pokémon and move.",
    "tera_types": "One row per Pokémon and Tera type. Smogon publishes them from 2024-08.",
    "happiness": "One row per Pokémon and happiness value.",
    "spreads": "One row per Pokémon, nature and EV spread.",
    "teammates": "One row per Pokémon and teammate.",
    "checks_counters": "One row per Pokémon and opponent: how the Pokémon fares when the two meet.",
    "metagame_styles": "One row per team style, format, month and cutoff.",
    "stalliness": "One row per bar of the stalliness histogram Smogon prints for each file.",
    "mega": "One row per Mega Evolution or Primal Reversion, format, month and cutoff (2014-11 to 2015-10).",
    "monotype_matchups": "One row per pair of types in Monotype: battles and win rate (from 2026-03).",
    "monotype_type_ranking": "One row per type in Monotype: Smogon's viability score (from 2026-03).",
}

COLUMNS = {
    "pokemon": {
        "pokemon_id": "Pokémon Showdown id: the name in lowercase, letters and digits only (`charizardmegax`).",
        "name": "Display name (`Charizard-Mega-X`).",
        "num": "National Pokédex number. 0 or below for what is not an official Pokémon (MissingNo., CAP, Pokéstar).",
        "base_species": "Name of the species the forme belongs to (`Charizard`).",
        "forme": "Forme name (`Mega-X`, `Wash`, `Alola`). Null for the base forme.",
        "gen": "Generation the forme first appeared in. Null for MissingNo.",
        "type1": "First type.",
        "type2": "Second type. Null for a single-type Pokémon.",
        "hp": "Base HP.",
        "atk": "Base Attack.",
        "def": "Base Defense.",
        "spa": "Base Special Attack.",
        "spd": "Base Special Defense.",
        "spe": "Base Speed.",
        "bst": "Base stat total: the sum of the six base stats.",
        "height_m": "Height in metres.",
        "weight_kg": "Weight in kilograms.",
        "is_cap": "True for the fan-made Pokémon of Smogon's Create-A-Pokémon project.",
    },
    "formats": {
        "month": _FILE_KEYS["month"],
        "format": "Format name as Smogon wrote it that month. With `month`, the join key to every other table.",
        "format_id": "The same name with its generation spelled out: `ou` is `gen6ou` until 2017-06. Not unique "
        "in 2016-12, where `randombattle` and `gen6randombattle` both exist.",
        "gen": "Generation of the format, 1 to 9.",
        "family": "`format_id` without the generation (`ou`, `ubers`, `vgc2015`), to follow a tier across "
        "generations. `smogondoubles` is filed under `doublesou`, its later name.",
        "battles": "Battles played in the format that month. Null when no file of the format gives the count."
        " The `monotype-mono<type>` formats are Monotype cut by team type, and repeat the count of the whole format.",
        "standard_cutoff": "The cutoff the Lite dataset keeps for this format and month: 1695 where Smogon publishes "
        "it (the OU and Doubles OU of the generation being played), 1630 otherwise.",
        "is_special_month": "True for a DLC or half-month folder (`2020-06-DLC1`, `2020-11-H1`). Those are slices "
        "of a month that is also published whole: adding them to it counts battles twice.",
        "lite_series": "Series of the Lite dataset this row belongs to, null when the format is not in it: "
        "`gen1ou` to `gen9ou`; `ubers`, `uu`, `ru`, `nu`, `doublesou`, `nationaldex`, `monotype` or `anythinggoes`, "
        "each followed from one generation to the next; `vgc` for the most played VGC format of the month.",
    },
    "files": {
        "table": "Table name, which is also the folder name.",
        "month": "Month of the file, as in the `month` column of the table.",
    },
    "cutoffs": {
        **_FILE_KEYS,
        "battles": "Battles played in the format that month. The same at every cutoff: the cutoff changes the "
        "weights, not the battles counted. 0 for four formats of 2025-05 that nobody played."
        " The `monotype-mono<type>` formats are Monotype cut by team type, and repeat the count of the whole format.",
        "avg_weight_per_team": "Average weight of a team at this cutoff, as printed at the top of the usage file.",
        "total_leads": "Total of the leads file: one lead per team, so twice the battles in singles. Null when the "
        "format has no leads file, which is the case of most doubles formats.",
        "stalliness_mean": "Mean stalliness of the teams. The more negative, the more offensive.",
        "pct_per_hash": "Share of the teams, in %, that one `#` of the stalliness histogram stands for.",
    },
    "usage": {
        **KEYS,
        "rank": "Rank in the file, 1 for the most used.",
        "usage_pct": "Weighted usage in %. Adds up to about 600 per file, a team having six Pokémon, and goes "
        "above 100 in formats where a team can field the same species several times. Null when every team of the "
        "file weighs 0.",
        "raw": "Unweighted count: times the Pokémon was on a team. Battles over in less than 3 turns (2 in doubles) "
        "are left out.",
        "raw_pct": "`raw` in %, on the same scale as `usage_pct`.",
        "real": "Unweighted count of the times the Pokémon actually came into play, not just sat in the team.",
        "real_pct": "`real` in %, on the same scale as `usage_pct`.",
    },
    "leads": {
        **KEYS,
        "rank": "Rank in the file, 1 for the most common lead.",
        "usage_pct": "Weighted share of the leads, in %. Adds up to 100 per file.",
        "raw": "Unweighted count: times the Pokémon was sent out first.",
        "raw_pct": "`raw` in % of the leads of the file.",
    },
    "movesets": {
        **KEYS,
        "raw_count": "Unweighted count: times the Pokémon was on a team. A few percent above `raw` in `usage`, "
        "which leaves out the shortest battles.",
        "usage": "Weighted usage as a fraction, not a percentage. Null before 2015-08.",
        "players": "Players who used the Pokémon. Null before 2015-07, like the three GXE columns.",
        "gxe_top": "Best GXE among those players. GXE is Showdown's estimate, in %, of a player's chances of "
        "beating a random opponent.",
        "gxe_p99": "GXE of the player at the top 1 % of them.",
        "gxe_p80": "GXE of the player at the top 20 % of them.",
    },
    "abilities": {**KEYS, "ability": "Ability, as a Showdown id (`intimidate`).", "weight": _WEIGHT},
    "items": {
        **KEYS,
        "item": "Held item, as a Showdown id (`leftovers`). `nothing` when the Pokémon holds no item.",
        "weight": _WEIGHT,
    },
    "moves": {
        **KEYS,
        "move": "Move, as a Showdown id (`stealthrock`). An empty string is an empty move slot. A set has up to "
        "four moves, so the shares of a Pokémon add up to 400 %, and the empty slot alone can go above 100 %.",
        "weight": _WEIGHT,
    },
    "tera_types": {
        **KEYS,
        "tera_type": "Tera type. `nothing` when the set has none.",
        "weight": _WEIGHT,
    },
    "happiness": {
        **KEYS,
        "happiness": "Happiness value of the set, 0 to 255 in the games. Hackmons players type in anything, hence "
        "a float, a few absurd values (`1e+308`) and nulls.",
        "weight": _WEIGHT,
    },
    "spreads": {
        **KEYS,
        "nature": "Nature, capitalised (`Adamant`).",
        "hp_ev": _EV.format(stat="HP"),
        "atk_ev": _EV.format(stat="Attack"),
        "def_ev": _EV.format(stat="Defense"),
        "spa_ev": _EV.format(stat="Special Attack"),
        "spd_ev": _EV.format(stat="Special Defense"),
        "spe_ev": _EV.format(stat="Speed"),
        "weight": _WEIGHT,
    },
    "teammates": {
        **KEYS,
        "teammate_id": "`pokemon_id` of the teammate. Null for the empty slot of a team of fewer than six.",
        "association_score": "Until 2021-03: weighted number of teams with both, minus the number the usage of the "
        "teammate predicts. Negative when they avoid each other. A count, not a ratio: it grows with the usage of "
        "the Pokémon, so only compare it within one Pokémon of one file. Null from 2021-04.",
        "count": "From 2021-04: weighted number of teams with both. Null until 2021-03.",
    },
    "checks_counters": {
        **KEYS,
        "opponent_id": "`pokemon_id` of the opposing Pokémon.",
        "n": "Weighted number of encounters between the two that ended with one of them knocked out or "
        "switched out. Each battle weighs as much as its lower rated player, and pairs at 20 or under are left out.",
        "p": "Share of those encounters, 0 to 1, where the Pokémon was knocked out or switched out.",
        "d": "Standard error of `p`: sqrt(p * (1 - p) / n).",
    },
    "metagame_styles": {
        **_FILE_KEYS,
        "style": "Team style, as Smogon's script tags it (`offense`, `stall`, `rain`, `weatherless`). A team can "
        "carry several tags.",
        "pct": "Weighted share of the teams with this tag, in %.",
    },
    "stalliness": {
        **_FILE_KEYS,
        "bin": "Stalliness value of the bar. The more negative, the more offensive. Smogon labels one bar in two; "
        "the others are filled in from their neighbours.",
        "hashes": "Number of `#` in the bar. Times `cutoffs.pct_per_hash`, it is the share of the teams in %.",
    },
    "mega": {
        **_FILE_KEYS,
        "pokemon_id": "Pokémon Showdown id of the Mega or Primal forme (`venusaurmega`, `charizardmegax`, "
        "`groudonprimal`). Joins to the `pokemon` table.",
        "pct": "Weighted usage of the forme in %, on the same scale as `usage.usage_pct`.",
    },
    "monotype_matchups": {
        **_FILE_KEYS,
        "type": "Type of the first team.",
        "opponent": "Type of the opposing team.",
        "battles": "Battles between the two types.",
        "win_pct": "Win rate of `type` against `opponent`, in %.",
    },
    "monotype_type_ranking": {
        **_FILE_KEYS,
        "type": "Type of the team.",
        "viability_score": "Viability score of the type, as Smogon prints it under the matchup chart.",
    },
}


def lite_columns(table: str) -> dict[str, str]:
    """Columns of a Lite file: the weight tables carry a percentage where the Complete ones have a raw weight."""
    if table not in WEIGHT_TABLES:
        return COLUMNS[table]
    return {**{column: text for column, text in COLUMNS[table].items() if column != "weight"}, "pct": _PCT}
