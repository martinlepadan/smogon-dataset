import json
from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.pokedex import build_pokemon, pokemon_id, unknown_names

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def pokemon() -> pl.DataFrame:
    return build_pokemon(json.loads((FIXTURES / "showdown/pokedex.json").read_text()))


def _row(pokemon: pl.DataFrame, pokemon_id: str) -> dict[str, object]:
    return pokemon.row(by_predicate=pl.col("pokemon_id") == pokemon_id, named=True)


def test_base_species(pokemon: pl.DataFrame) -> None:
    bulbasaur = _row(pokemon, "bulbasaur")
    assert bulbasaur["name"] == "Bulbasaur"
    assert bulbasaur["base_species"] == "Bulbasaur"
    assert bulbasaur["forme"] is None
    assert (bulbasaur["type1"], bulbasaur["type2"]) == ("Grass", "Poison")
    assert bulbasaur["bst"] == 318
    assert _row(pokemon, "floetteeternal")["type2"] is None


def test_forme_keeps_its_own_stats(pokemon: pl.DataFrame) -> None:
    mega = _row(pokemon, "charizardmegax")
    assert (mega["base_species"], mega["forme"]) == ("Charizard", "Mega-X")
    assert (mega["type1"], mega["type2"]) == ("Fire", "Dragon")
    assert mega["bst"] > _row(pokemon, "charizard")["bst"]


def test_cosmetic_forme_takes_the_base_species_data(pokemon: pl.DataFrame) -> None:
    east, base = _row(pokemon, "gastrodoneast"), _row(pokemon, "gastrodon")
    assert east["name"] == "Gastrodon-East"
    assert east["forme"] == "East"
    for column in ("num", "gen", "type1", "type2", "bst", "weight_kg"):
        assert east[column] == base[column]


@pytest.mark.parametrize(
    ("pokemon_id", "gen"),
    [
        ("bulbasaur", 1),
        ("gastrodon", 4),
        ("charizardmegax", 6),
        ("groudonprimal", 6),
        ("raichualola", 7),
        ("venusaurgmax", 8),
        ("typhlosionhisui", 8),
        ("taurospaldeablaze", 9),
        ("greattusk", 9),
        # Explicit in the pokedex: a Mega from Legends Z-A, a CAP made for gen 4.
        ("falinksmega", 9),
        ("syclant", 4),
        ("missingno", None),
    ],
)
def test_generation(pokemon: pl.DataFrame, pokemon_id: str, gen: int | None) -> None:
    assert _row(pokemon, pokemon_id)["gen"] == gen


def test_is_cap(pokemon: pl.DataFrame) -> None:
    assert pokemon.filter("is_cap")["pokemon_id"].to_list() == ["syclant"]


def test_pokemon_id_of_names_as_the_stats_spell_them() -> None:
    names = ["Great Tusk", "Farfetch'd", "NidoranF", "Rotom-Wash", "Flabebe", "Floette-Eternal-Flower", "Charizard X"]
    ids = pl.DataFrame({"name": names}).select(pokemon_id(pl.col("name")))["name"].to_list()
    assert ids == ["greattusk", "farfetchd", "nidoranf", "rotomwash", "flabebe", "floetteeternal", "charizardmegax"]


def test_unknown_names(pokemon: pl.DataFrame, tmp_path: Path) -> None:
    pl.DataFrame({"pokemon": ["Bulbasaur", "Great Tusk", "Not A Pokemon"]}).write_parquet(tmp_path / "usage.parquet")
    pl.DataFrame({"opponent": ["Rotom-Wash", "Also Unknown"]}).write_parquet(tmp_path / "chaos_checks.parquet")
    assert unknown_names(pokemon, tmp_path)["name"].to_list() == ["Also Unknown", "Not A Pokemon"]
