import shutil
from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.fetch import SmogonClient
from smogon_dataset.inventory import walk_month
from smogon_dataset.sync import MonthFailedError, parse_file, sync_month

FIXTURES = Path(__file__).parent / "fixtures"


def test_sync_month_from_fixtures(tmp_path: Path) -> None:
    cache = tmp_path / "raw"
    shutil.copytree(FIXTURES / "2026-09", cache / "2026-09")
    inventory = _inventory_of(cache, "2026-09")

    with SmogonClient(cache_dir=cache) as client:
        counts = sync_month(client, inventory, out_dir=tmp_path / "interim")
        assert client.requests_made == 0

    out = tmp_path / "interim/2026-09"
    assert {p.stem for p in out.iterdir()} == {
        "chaos_info",
        "chaos_pokemon",
        "chaos_weights",
        "chaos_checks",
        "usage",
        "leads",
        "metagame",
        "metagame_stalliness",
        "monotype_matchups",
        "monotype_type_ranking",
    }
    assert counts["chaos_info"] == 2
    usage = pl.read_parquet(out / "usage.parquet")
    assert usage.columns[:3] == ["month", "format", "cutoff"]
    assert set(usage["format"]) == {"gen9nfe", "gen9monotype-monorock"}
    # Raw data files are gone, nothing is left but the empty folders.
    assert not [p for p in (cache / "2026-09").rglob("*") if p.is_file()]


def _inventory_of(cache: Path, month: str) -> pl.DataFrame:
    """Build an inventory from the files on disk, the way the crawler would from listings."""
    for folder in [cache / month, *[p for p in (cache / month).rglob("*") if p.is_dir()]]:
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir())
        lines = [f'<a href="{n}">{n}</a>   01-Oct-2026 14:40   {"-" if n.endswith("/") else 1}' for n in names]
        (folder / "index.html").write_text("<pre>" + "\n".join(lines) + "</pre>")
    with SmogonClient(cache_dir=cache) as client:
        rows = list(walk_month(client, month))
    for index in cache.rglob("index.html"):
        index.unlink()
    return pl.DataFrame(rows).filter(pl.col("file") != "index.html")


def test_sync_month_reports_every_failure(tmp_path: Path) -> None:
    cache = tmp_path / "raw"
    shutil.copytree(FIXTURES / "2026-09", cache / "2026-09")
    inventory = _inventory_of(cache, "2026-09")
    for broken in ["leads/gen9nfe-0.txt", "metagame/gen9nfe-0.txt"]:
        (cache / "2026-09" / broken).write_text("garbage\n")

    with SmogonClient(cache_dir=cache) as client, pytest.raises(MonthFailedError) as failure:
        sync_month(client, inventory, out_dir=tmp_path / "interim")

    assert len(failure.value.errors) == 2
    assert (tmp_path / "interim/2026-09.errors.txt").read_text().count("garbage") == 2
    assert not (tmp_path / "interim/2026-09").exists()
    # Nothing was deleted: fixing the parser and re-running needs no download.
    assert (cache / "2026-09/chaos/gen9nfe-0.json").exists()


def test_moveset_report_in_place_of_a_usage_file_is_skipped(tmp_path: Path) -> None:
    # 2016-10/cap-0.txt
    report = " +-----------+ \n | Colossoil | \n +-----------+ \n | Raw count: 8998 | \n | Avg. weight: 1.0 | \n"
    path = tmp_path / "cap-0.txt"
    path.write_text(report)
    row = {"month": "2016-10", "format": "cap", "cutoff": 0, "section": "", "ext": "txt"}
    assert parse_file(path, row) == {}
