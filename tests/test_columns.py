import pytest

from smogon_dataset.columns import COLUMNS, TABLES, lite_columns
from smogon_dataset.validate import SCHEMAS, Formats, Pokemon

MODELS = {**SCHEMAS, "pokemon": Pokemon, "formats": Formats}


@pytest.mark.parametrize("table", sorted(MODELS))
def test_described_columns_are_the_ones_validate_checks_in_the_same_order(table: str) -> None:
    assert list(COLUMNS[table]) == list(MODELS[table].to_schema().columns)


def test_every_table_has_a_description_and_every_column_too() -> None:
    # files.parquet is written by stage_complete and has no model.
    assert set(COLUMNS) == set(TABLES) == {*MODELS, "files"}
    assert all(text for columns in COLUMNS.values() for text in columns.values())


def test_lite_weight_tables_have_pct_where_complete_has_weight() -> None:
    assert list(lite_columns("moves")) == ["month", "format", "cutoff", "pokemon_id", "move", "pct"]
    assert lite_columns("usage") == COLUMNS["usage"]
