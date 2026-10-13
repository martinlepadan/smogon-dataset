import json
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from smogon_dataset.cards import LITE_SLUG, complete_slug
from smogon_dataset.formats import build_formats, read_battles
from smogon_dataset.inventory import SCHEMA
from smogon_dataset.lite import build_lite
from smogon_dataset.normalize import normalize_month
from smogon_dataset.pokedex import build_pokemon
from smogon_dataset.update import (
    PublishedYearError,
    build_update,
    fetch_published,
    find_month,
    is_settled,
    publish_update,
    unstage_year,
)
from smogon_dataset.validate import ValidationError
from test_normalize import _canonical_month

FIXTURES = Path(__file__).parent / "fixtures"
POKEMON = build_pokemon(json.loads((FIXTURES / "showdown/pokedex.json").read_text()))
YEARS = ["2025", "2026"]


class FakeKaggle:
    """Kaggle as a folder: <root>/<slug>/ holds the files of a dataset."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.sent: list[tuple[str, str, bool]] = []

    def exists(self, slug: str) -> bool:
        return (self.root / slug).exists()

    def fetch_file(self, slug: str, name: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        return Path(shutil.copy(self.root / slug / name, dest_dir / name))

    def fetch_all(self, slug: str, dest_dir: Path) -> None:
        shutil.copytree(self.root / slug, dest_dir)

    def send(self, dataset_dir: Path, notes: str, *, create: bool = False) -> None:
        self.sent.append((dataset_dir.name, notes, create))


def _inventory(month: str) -> pl.DataFrame:
    rows = [
        {
            "month": month,
            "section": "",
            "file": f"gen9ou-{cutoff}.txt",
            "format": "gen9ou",
            "cutoff": cutoff,
            "ext": "txt",
            "size": 1,
            "modified": datetime(2026, 10, 1, 14, 40),
        }
        for cutoff in (0, 1500, 1695, 1825)
    ]
    return pl.DataFrame(rows, schema=SCHEMA)


def _synced_month(interim: Path, month: str) -> None:
    _canonical_month(interim / month)
    # Its second format was never played: as a Lite series it would have no ranking. One format is enough here.
    info = interim / month / "chaos_info.parquet"
    pl.read_parquet(info).filter(format="gen9ou").write_parquet(info)


def _run_month(work_dir: Path, month: str, kaggle: FakeKaggle) -> None:
    if not (work_dir / "interim" / month).exists():
        _synced_month(work_dir / "interim", month)
    fetch_published(kaggle, month, work_dir)
    build_update(month, _inventory(month), POKEMON, YEARS, work_dir)


def _kaggle_with(tmp_path: Path, months: list[str]) -> FakeKaggle:
    """A fake Kaggle that got `months` one update at a time, starting from an empty Lite."""
    kaggle = FakeKaggle(tmp_path / "kaggle")
    _first_lite(tmp_path / "seed", kaggle.root / LITE_SLUG)
    for month in months:
        work_dir = tmp_path / f"work-{month}"
        _run_month(work_dir, month, kaggle)
        _publish_to(kaggle, work_dir, month)
    return kaggle


def _first_lite(seed: Path, lite: Path) -> None:
    """The Lite of the first full build, one month long: the update always has one to start from."""
    _synced_month(seed / "interim", "2025-12")
    formats = build_formats(_inventory("2025-12"), read_battles(seed / "interim"))
    normalize_month(seed / "interim/2025-12", POKEMON, formats, seed / "complete")
    build_lite(seed / "complete", POKEMON, formats, lite)


def _publish_to(kaggle: FakeKaggle, work_dir: Path, month: str) -> None:
    """Do what Kaggle does with an upload: the staged folders replace the datasets."""
    for staged, slug in (("lite", LITE_SLUG), (f"complete-{month[:4]}", complete_slug(month[:4]))):
        shutil.rmtree(kaggle.root / slug, ignore_errors=True)
        shutil.copytree(work_dir / "kaggle" / staged, kaggle.root / slug)


def _find(kaggle: FakeKaggle, server_months: list[str], tmp_path: Path, wanted: str | None = None) -> str | None:
    return find_month(server_months, kaggle, wanted, tmp_path / "probe")


def test_the_month_to_add_is_the_newest_one_kaggle_lacks(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])

    assert _find(kaggle, ["2026-07", "2026-08", "2026-09"], tmp_path) == "2026-09"
    assert _find(kaggle, ["2026-07", "2026-08", "2026-09", "2026-09-DLC1"], tmp_path) == "2026-09-DLC1"
    # A new year has no dataset yet, and the December before it is still looked at.
    assert _find(kaggle, ["2026-08", "2027-01"], tmp_path) == "2027-01"
    assert _find(kaggle, ["2025-12", "2026-08"], tmp_path) == "2025-12"


def test_nothing_to_add_when_kaggle_has_every_month(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])

    assert _find(kaggle, ["2026-08"], tmp_path) is None
    assert _find(kaggle, ["2026-08"], tmp_path, wanted="2026-08") is None


def test_a_month_can_be_asked_for_if_smogon_has_it(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])

    assert _find(kaggle, ["2026-07", "2026-08", "2026-09"], tmp_path, wanted="2026-07") == "2026-07"
    with pytest.raises(ValueError, match="2026-10 is not a folder"):
        _find(kaggle, ["2026-08", "2026-09"], tmp_path, wanted="2026-10")


def test_a_month_only_the_complete_got_is_done_again(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    work_dir = tmp_path / "work"
    _run_month(work_dir, "2026-09", kaggle)
    shutil.rmtree(kaggle.root / complete_slug("2026"))
    shutil.copytree(work_dir / "kaggle/complete-2026", kaggle.root / complete_slug("2026"))

    assert _find(kaggle, ["2026-08", "2026-09"], tmp_path) == "2026-09"

    # The year already holds the month: the fresh files replace it, nothing is doubled.
    _run_month(tmp_path / "again", "2026-09", kaggle)
    year = tmp_path / "again/kaggle/complete-2026"
    assert pl.read_parquet(year / "files.parquet").filter(table="usage")["month"].to_list() == ["2026-08", "2026-09"]
    assert pl.read_parquet(year / "formats.parquet")["month"].to_list() == ["2026-08", "2026-09"]


def test_a_special_month_is_published_once_its_year_has_it(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08", "2026-08-DLC1"])

    assert _find(kaggle, ["2026-08", "2026-08-DLC1"], tmp_path) is None
    lite_months = pl.read_parquet(kaggle.root / LITE_SLUG / "usage.parquet")["month"]
    assert lite_months.unique(maintain_order=True).to_list() == ["2025-12", "2026-08"]
    files = pl.read_parquet(kaggle.root / complete_slug("2026") / "files.parquet")
    assert set(files["month"]) == {"2026-08", "2026-08-DLC1"}


def test_a_month_is_settled_a_day_after_its_last_file() -> None:
    inventory = _inventory("2026-09")
    assert not is_settled(inventory, datetime(2026, 10, 2, 6, 0))
    assert is_settled(inventory, datetime(2026, 10, 3, 6, 0))


def test_update_adds_the_month_to_the_lite_and_to_its_year(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    published_usage = pl.read_parquet(kaggle.root / LITE_SLUG / "usage.parquet")
    work_dir = tmp_path / "work"

    _run_month(work_dir, "2026-09", kaggle)

    staged = work_dir / "kaggle"
    # The canonical month has no item and no Tera type.
    for table in ("cutoffs", "usage", "abilities", "moves"):
        months = pl.read_parquet(staged / f"lite/{table}.parquet")["month"].unique(maintain_order=True).to_list()
        assert months == ["2025-12", "2026-08", "2026-09"]
    usage = pl.read_parquet(staged / "lite/usage.parquet")
    assert usage.filter(pl.col("month") < "2026-09").equals(published_usage)
    assert pl.read_csv(staged / "lite/usage.csv").height == usage.height
    assert pl.read_parquet(staged / "lite/formats.parquet").select("month", "format", "lite_series").rows() == [
        (month, "gen9ou", "gen9ou") for month in ("2025-12", "2026-08", "2026-09")
    ]

    year = staged / "complete-2026"
    files = pl.read_parquet(year / "files.parquet")
    assert set(files["month"]) == {"2026-08", "2026-09"}
    assert sorted(str(path.relative_to(year)) for path in year.glob("*/*.parquet")) == sorted(
        f"{table}/{month}.parquet" for table, month in files.rows()
    )
    old_month = kaggle.root / complete_slug("2026") / "usage/2026-08.parquet"
    assert (year / "usage/2026-08.parquet").read_bytes() == old_month.read_bytes()
    assert pl.read_parquet(year / "formats.parquet")["month"].unique(maintain_order=True).to_list() == [
        "2026-08",
        "2026-09",
    ]
    assert pl.read_parquet(year / "pokemon.parquet").equals(POKEMON)

    # The cards link to every year, staged here or not.
    lite_card = json.loads((staged / "lite/dataset-metadata.json").read_text())
    assert complete_slug("2025") in lite_card["description"]
    year_card = json.loads((year / "dataset-metadata.json").read_text())
    assert year_card["id"].endswith(complete_slug("2026"))
    assert complete_slug("2025") in year_card["description"]
    assert year_card["expectedUpdateFrequency"] == "monthly"


def test_a_january_month_starts_its_year(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2025-12"])
    work_dir = tmp_path / "work"

    _run_month(work_dir, "2026-01", kaggle)
    publish_update(kaggle, "2026-01", work_dir)

    year = work_dir / "kaggle/complete-2026"
    assert set(pl.read_parquet(year / "files.parquet")["month"]) == {"2026-01"}
    assert not (work_dir / "kaggle/complete-2025").exists()
    notes = "Add 2026-01: 1 formats, 5 battles"
    assert kaggle.sent == [("complete-2026", notes, True), ("lite", notes, False)]


def test_publish_sends_the_year_then_the_lite_and_no_lite_for_a_special_month(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    work_dir = tmp_path / "work"

    _run_month(work_dir, "2026-09", kaggle)
    publish_update(kaggle, "2026-09", work_dir)
    assert [(name, create) for name, _, create in kaggle.sent] == [("complete-2026", False), ("lite", False)]

    kaggle.sent.clear()
    _run_month(tmp_path / "special", "2026-09-DLC1", kaggle)
    publish_update(kaggle, "2026-09-DLC1", tmp_path / "special")
    assert [name for name, _, _ in kaggle.sent] == ["complete-2026"]


def test_a_month_that_fails_validation_leaves_nothing_staged(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    work_dir = tmp_path / "work"
    _synced_month(work_dir / "interim", "2026-09")
    # 700 % of usage in one file.
    usage = pl.read_parquet(work_dir / "interim/2026-09/usage.parquet")
    usage.with_columns(usage_pct=pl.lit(350.0)).write_parquet(work_dir / "interim/2026-09/usage.parquet")

    with pytest.raises(ValidationError, match="2026-09/usage"):
        _run_month(work_dir, "2026-09", kaggle)

    assert not (work_dir / "kaggle").exists()


def test_update_refuses_a_pokedex_that_lost_a_published_id(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    work_dir = tmp_path / "work"
    _synced_month(work_dir / "interim", "2026-09")
    fetch_published(kaggle, "2026-09", work_dir)

    with pytest.raises(ValidationError, match="rotomwash"):
        build_update(
            "2026-09", _inventory("2026-09"), POKEMON.filter(pl.col("pokemon_id") != "rotomwash"), YEARS, work_dir
        )

    assert not (work_dir / "kaggle").exists()


def test_a_download_missing_a_file_of_the_year_stops_the_update(tmp_path: Path) -> None:
    kaggle = _kaggle_with(tmp_path, ["2026-08"])
    year_dir = tmp_path / "published/complete-2026"
    kaggle.fetch_all(complete_slug("2026"), year_dir)
    (year_dir / "moves/2026-08.parquet").unlink()

    with pytest.raises(PublishedYearError, match=r"missing \[\('moves', '2026-08'\)\]"):
        unstage_year(year_dir, tmp_path / "complete", rebuilt="2026-09")

    assert not (tmp_path / "complete").exists()
