from pathlib import Path

import polars as pl

from smogon_dataset.fetch import SmogonClient
from smogon_dataset.inventory import standard_cutoffs, walk_month


def _listing(*names: str) -> str:
    lines = [f'<a href="{n}">{n}</a>   01-Oct-2026 14:40   {"-" if n.endswith("/") else 100}' for n in names]
    return "<pre>" + "\n".join(lines) + "</pre>"


def test_walk_month_recurses_and_parses_names(tmp_path: Path) -> None:
    # Pre-filled cache: the client never touches the network.
    (tmp_path / "2026-09/monotype").mkdir(parents=True)
    (tmp_path / "2026-09/index.html").write_text(_listing("monotype/", "gen9ou-1695.txt"))
    (tmp_path / "2026-09/monotype/index.html").write_text(_listing("gen9monotype-monobug-0.json", "readme.txt"))

    with SmogonClient(cache_dir=tmp_path) as client:
        rows = {r["file"]: r for r in walk_month(client, "2026-09")}
        assert client.requests_made == 0

    assert rows["gen9ou-1695.txt"] | {"modified": None} == {
        "month": "2026-09",
        "section": "",
        "file": "gen9ou-1695.txt",
        "format": "gen9ou",
        "cutoff": 1695,
        "ext": "txt",
        "size": 100,
        "modified": None,
    }
    mono = rows["gen9monotype-monobug-0.json"]
    assert (mono["section"], mono["format"], mono["cutoff"]) == ("monotype", "gen9monotype-monobug", 0)
    assert (rows["readme.txt"]["format"], rows["readme.txt"]["cutoff"]) == (None, None)


def test_standard_cutoff_follows_the_files() -> None:
    inventory = pl.DataFrame(
        {
            "month": ["2022-10"] * 4 + ["2022-11"] * 4,
            "section": [""] * 8,
            "format": ["gen8ou", "gen8ou", "gen8uu", "gen8uu", "gen8ou", "gen8ou", "gen9ou", "gen9ou"],
            "cutoff": [1500, 1695, 1500, 1630, 1630, 1760, 1695, 1825],
        }
    )
    assert standard_cutoffs(inventory).rows() == [
        ("2022-10", "gen8ou", 1695),
        ("2022-10", "gen8uu", 1630),
        ("2022-11", "gen8ou", 1630),
        ("2022-11", "gen9ou", 1695),
    ]
