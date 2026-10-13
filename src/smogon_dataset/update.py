"""The monthly update: add one month to the datasets on Kaggle, from a machine that holds nothing.

Only the new month is downloaded from smogon.com. The rest comes back from Kaggle: the Lite
tables, and the Complete dataset of the month's year, which has to be sent whole again.
"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from smogon_dataset.cards import LITE_SLUG, complete_slug
from smogon_dataset.config import DATA_DIR
from smogon_dataset.formats import build_formats, read_battles
from smogon_dataset.kaggle_api import KaggleDatasets
from smogon_dataset.lite import build_lite
from smogon_dataset.normalize import normalize_month
from smogon_dataset.publish import LITE_TABLES, stage_complete, stage_lite, write_cards
from smogon_dataset.validate import ValidationError, check_formats, check_pokemon

# Its own tree, so that running the update next to a full local build overwrites nothing of it.
UPDATE_DIR = DATA_DIR / "update"

# Smogon usually uploads a month within a minute, but a few took days to get all their files.
SETTLED_AFTER = timedelta(days=1)


class PublishedYearError(Exception):
    pass


def is_special(month: str) -> bool:
    return len(month) > len("2020-11")


def published_months(kaggle: KaggleDatasets, years: list[str], dest_dir: Path) -> set[str]:
    """Months of `years` that Kaggle has in full: in the Complete of their year and in the Lite.

    The two are sent one after the other. A month only one of them has is a failed upload,
    and counts as not published so that the next run does it again.
    """
    in_lite = set(pl.read_parquet(kaggle.fetch_file(LITE_SLUG, "formats.parquet", dest_dir / "lite"))["month"])
    in_complete: set[str] = set()
    for year in years:
        slug = complete_slug(year)
        if kaggle.exists(slug):
            files = pl.read_parquet(kaggle.fetch_file(slug, "files.parquet", dest_dir / f"complete-{year}"))
            in_complete |= set(files["month"])
    # The Lite leaves the special months out.
    return {month for month in in_complete if is_special(month) or month in in_lite}


def find_month(
    server_months: list[str], kaggle: KaggleDatasets, wanted: str | None = None, work_dir: Path = UPDATE_DIR
) -> str | None:
    """The month to add: `wanted`, or the newest folder of smogon.com/stats that Kaggle lacks.

    None when Kaggle already has it: a published month is never downloaded again.
    """
    if wanted and wanted not in server_months:
        raise ValueError(f"{wanted} is not a folder of smogon.com/stats")
    # Two years, so that a December missed in January is still seen in February.
    years = [wanted[:4]] if wanted else sorted({month[:4] for month in server_months})[-2:]
    published = published_months(kaggle, years, work_dir / "published")
    candidates = [wanted] if wanted else [month for month in server_months if month[:4] in years]
    return max((month for month in candidates if month not in published), default=None)


def is_settled(inventory: pl.DataFrame, now: datetime) -> bool:
    """False while the newest file of the month is too recent for the folder to be trusted complete."""
    return bool(inventory.select(pl.lit(now) - pl.col("modified").max() > SETTLED_AFTER).item())


def fetch_published(kaggle: KaggleDatasets, month: str, work_dir: Path = UPDATE_DIR) -> None:
    """Download to <work_dir>/published what the update builds on."""
    published = work_dir / "published"
    shutil.rmtree(published, ignore_errors=True)
    # Parquet only: the CSV are ten times the size and get written again from it.
    for table in LITE_TABLES:
        kaggle.fetch_file(LITE_SLUG, f"{table}.parquet", published / "lite")
    year = month[:4]
    # A January month has no dataset to join yet.
    if kaggle.exists(complete_slug(year)):
        kaggle.fetch_all(complete_slug(year), published / f"complete-{year}")


def build_update(
    month: str, inventory: pl.DataFrame, pokemon: pl.DataFrame, years: list[str], work_dir: Path = UPDATE_DIR
) -> None:
    """Lay out in <work_dir>/kaggle the Lite and the year of `month`, ready to be sent.

    Expects the month synced in <work_dir>/interim and fetch_published done. `inventory`
    lists the files of the month, `years` every Complete dataset the cards link to.
    Anything that fails a check raises: nothing is half ready.
    """
    interim, complete, published = work_dir / "interim", work_dir / "complete", work_dir / "published"
    for stale in (complete, work_dir / "lite", work_dir / "kaggle"):
        shutil.rmtree(stale, ignore_errors=True)

    check_pokemon(pokemon)
    # The old months are not normalized again: an id Showdown renamed or dropped would
    # leave their rows pointing at nothing.
    gone = pl.read_parquet(published / "lite/pokemon.parquet").join(pokemon, on="pokemon_id", how="anti")
    if gone.height:
        raise ValidationError(
            f"pokemon: ids of the published months missing from today's pokedex: {gone['pokemon_id'].to_list()}"
        )
    month_formats = build_formats(inventory, read_battles(interim))
    check_formats(month_formats)
    normalize_month(interim / month, pokemon, month_formats, complete)

    # Before the rest of the year comes back into `complete`: the Lite derives again every
    # month it finds there, and takes the others as published.
    build_lite(complete, pokemon, month_formats, work_dir / "lite", published / "lite")

    year_formats = month_formats
    published_year = published / f"complete-{month[:4]}"
    if published_year.exists():
        unstage_year(published_year, complete, rebuilt=month)
        before = pl.read_parquet(published_year / "formats.parquet").filter(pl.col("month") != month)
        year_formats = pl.concat([before, month_formats]).sort("month", "format")
    formats_path = work_dir / "formats.parquet"
    year_formats.write_parquet(formats_path)

    stage_complete(complete, work_dir / "lite/pokemon.parquet", formats_path, work_dir / "kaggle")
    stage_lite(work_dir / "lite", work_dir / "kaggle")
    write_cards(work_dir / "kaggle", years)


def unstage_year(year_dir: Path, complete_dir: Path, rebuilt: str) -> None:
    """Move a downloaded year back to <month>/<table>.parquet, the layout stage_complete starts from.

    `rebuilt` is the month being added: after a failed upload the year may already have it,
    and the fresh one wins.
    """
    listed = set(pl.read_parquet(year_dir / "files.parquet").rows())
    found = {(table_file.parent.name, table_file.stem) for table_file in year_dir.glob("*/*.parquet")}
    # Sending the year back without one of its files would drop that file from Kaggle.
    if found != listed:
        raise PublishedYearError(
            f"{year_dir.name}: the download does not match its files.parquet, "
            f"missing {sorted(listed - found)}, unlisted {sorted(found - listed)}"
        )
    for table, month in found:
        if month != rebuilt:
            moved = complete_dir / month / f"{table}.parquet"
            moved.parent.mkdir(parents=True, exist_ok=True)
            (year_dir / table / f"{month}.parquet").rename(moved)


def publish_update(kaggle: KaggleDatasets, month: str, work_dir: Path = UPDATE_DIR) -> None:
    """Send what build_update staged: the year of `month`, then the Lite."""
    year = month[:4]
    year_dir = work_dir / f"kaggle/complete-{year}"
    added = pl.read_parquet(year_dir / "formats.parquet").filter(pl.col("month") == month)
    notes = f"Add {month}: {added.height} formats, {added['battles'].sum():,} battles"
    kaggle.send(year_dir, notes, create=not kaggle.exists(complete_slug(year)))
    # Nothing of a special month goes into the Lite.
    if not is_special(month):
        kaggle.send(work_dir / "kaggle/lite", notes)
