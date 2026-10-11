from pathlib import Path

import pytest

from smogon_dataset.parsers.text import (
    UnparsedLineError,
    parse_leads,
    parse_matchups,
    parse_mega,
    parse_metagame,
    parse_usage,
)

FIXTURES = Path(__file__).parent / "fixtures"


# Usage files sit at the root of a month or of its monotype/ folder.
USAGE = sorted(p for p in FIXTURES.glob("**/*.txt") if p.parent.name == "monotype" or p.parent.parent == FIXTURES)
LEADS = sorted(FIXTURES.glob("**/leads/*.txt"))
METAGAME = sorted(FIXTURES.glob("**/metagame/*.txt"))


def _id(path: Path) -> str:
    return str(path.relative_to(FIXTURES))


@pytest.mark.parametrize("path", USAGE, ids=_id)
def test_usage(path: Path) -> None:
    df = parse_usage(path.read_text())
    assert df["rank"].to_list() == list(range(1, df.height + 1))
    assert df["battles"][0] > 0
    # Each team has 6 slots, so usage sums to ~600% (less when teams are short).
    assert 0 < df["usage_pct"].sum() <= 600.5


@pytest.mark.parametrize("path", LEADS, ids=_id)
def test_leads(path: Path) -> None:
    df = parse_leads(path.read_text())
    assert df["rank"].to_list() == list(range(1, df.height + 1))
    # Monotype sub-formats report the leads of the whole monotype metagame.
    if "monotype" not in path.parts:
        assert df["raw"].sum() == df["total_leads"][0]


@pytest.mark.parametrize("path", METAGAME, ids=_id)
def test_metagame(path: Path) -> None:
    styles, stalliness = parse_metagame(path.read_text())
    assert styles.height > 0
    assert stalliness["bin"].diff().drop_nulls().unique().len() == 1
    assert stalliness["pct_per_hash"].null_count() == 0


def test_stalliness_bins_in_2014() -> None:
    _, stalliness = parse_metagame((FIXTURES / "2014-11/metagame/stabmons-0.txt").read_text())
    assert stalliness.row(0) == (-2.0, 9, -0.466, 0.82)
    assert stalliness.row(1)[:2] == (-1.5, 14)


def test_mega() -> None:
    df = parse_mega((FIXTURES / "2014-11/mega/stabmons-0.txt").read_text())
    assert df.row(0) == ("Tyranitar", 10.43426)
    assert "Charizard Y" in df["pokemon"].to_list()


def test_matchups() -> None:
    path = next(FIXTURES.glob("2026-09/monotype/matchupcharts/*.txt"))
    matrix, ranking = parse_matchups(path.read_text())
    assert matrix.height == 18 * 18
    assert matrix.filter(type="electric", opponent="ground").row(0) == ("electric", "ground", 17.0, 22.078)
    assert ranking.height == 18
    assert ranking.row(0) == ("bug", 4.357)


def test_unknown_line_fails_loudly() -> None:
    with pytest.raises(UnparsedLineError, match="Surprise"):
        parse_leads(" Total leads: 1\n Surprise section\n")


def test_nan_becomes_null() -> None:
    # gen9monocolor 2026-09 at 1630: one battle, every team weighs 0.
    styles, stalliness = parse_metagame("weatherless.......NaN%\nstall.............NaN%\n")
    assert styles.rows() == [("weatherless", None), ("stall", None)]
    assert stalliness.is_empty()
    usage = parse_usage(
        "Total battles: 1\nAvg. weight/team: 0.000\n"
        "| 1    | Mienshao           |      NaN% | 1      | 50.000% | 1      | 54.545% |\n"
    )
    assert usage.row(0)[:4] == (1, "Mienshao", None, 1)


def test_empty_usage_file_gives_an_empty_table() -> None:
    # 2015-03/randombattle-1695.txt is served empty.
    assert parse_usage("").is_empty()
    assert parse_leads("").is_empty()
