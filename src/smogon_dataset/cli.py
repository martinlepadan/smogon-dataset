import json
import time
from typing import Annotated

import polars as pl
import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from smogon_dataset import __version__
from smogon_dataset.config import INTERIM_DIR, REQUEST_DELAY_S
from smogon_dataset.fetch import SmogonClient
from smogon_dataset.formats import FORMATS_PATH, build_formats, read_battles
from smogon_dataset.inventory import INVENTORY_PATH, build_inventory
from smogon_dataset.normalize import UnknownPokemonError, is_normalized, normalize_month
from smogon_dataset.pokedex import POKEMON_PATH, build_pokemon, download_pokedex, unknown_names
from smogon_dataset.sync import MonthFailedError, is_synced, month_files, sync_month
from smogon_dataset.validate import ValidationError, check_formats, check_pokemon

app = typer.Typer(help="Smogon usage stats pipeline.", no_args_is_help=True)


# Without a callback, Typer collapses a single-command app into that command.
@app.callback()
def main() -> None:
    pass


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)


@app.command()
def inventory(
    months: Annotated[list[str] | None, typer.Argument(help="Months to crawl, e.g. 2026-09. Default: all.")] = None,
) -> None:
    """Crawl the archive listings and write one row per file to data/interim/inventory.parquet.

    With months, only their rows are replaced: the rest of the inventory is kept.
    """
    previous = pl.read_parquet(INVENTORY_PATH) if INVENTORY_PATH.exists() else None
    with SmogonClient() as client:
        df = build_inventory(client, months, previous)
        INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(INVENTORY_PATH)
        typer.echo(f"{df.height} files, {df['month'].n_unique()} months, {client.requests_made} requests")
        typer.echo(f"-> {INVENTORY_PATH}")


@app.command()
def pokemon() -> None:
    """Download the Showdown pokedex, write data/interim/pokemon.parquet and check the synced months against it."""
    table = build_pokemon(json.loads(download_pokedex().read_text()))
    check_pokemon(table)
    table.write_parquet(POKEMON_PATH)
    typer.echo(f"{table.height} formes -> {POKEMON_PATH}")

    unknown: dict[str, list[str]] = {}
    for month_dir in sorted(INTERIM_DIR.iterdir()):
        if month_dir.is_dir() and month_dir.suffix != ".part":
            for name in unknown_names(table, month_dir)["name"]:
                unknown.setdefault(name, []).append(month_dir.name)
    for name, months in unknown.items():
        typer.echo(f"  not in the pokedex: {name!r}, {len(months)} month(s) from {months[0]} to {months[-1]}")
    if unknown:
        raise typer.Exit(1)


@app.command()
def formats() -> None:
    """Write data/interim/formats.parquet: generation, family and Lite series of every format of every month."""
    table = build_formats(pl.read_parquet(INVENTORY_PATH), read_battles(INTERIM_DIR))
    check_formats(table)
    table.write_parquet(FORMATS_PATH)
    lite = table.filter(pl.col("lite_series").is_not_null())
    typer.echo(f"{table.height} (month, format) pairs, {lite.height} in the Lite series -> {FORMATS_PATH}")


@app.command()
def normalize(
    months: Annotated[
        list[str] | None, typer.Argument(help="Months to normalize. Default: all those not done.")
    ] = None,
) -> None:
    """Turn the canonical tables of synced months into validated Complete tables, in data/complete/<month>/.

    A month that breaks a validation rule is not written: the run says why and moves on.
    """
    pokemon_table, formats_table = pl.read_parquet(POKEMON_PATH), pl.read_parquet(FORMATS_PATH)
    synced = sorted(p.name for p in INTERIM_DIR.iterdir() if p.is_dir() and p.suffix != ".part")
    todo = months or [month for month in synced if not is_normalized(month)]
    failed = 0
    with Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn()) as progress:
        for month in progress.track(todo, description="normalize"):
            try:
                normalize_month(INTERIM_DIR / month, pokemon_table, formats_table)
            except (ValidationError, UnknownPokemonError) as exc:
                failed += 1
                progress.console.print(f"FAILED {exc}")
    if failed:
        typer.echo(f"{failed} month(s) not written")
        raise typer.Exit(1)


@app.command()
def sync(
    months: Annotated[list[str] | None, typer.Argument(help="Months to sync. Default: all those not synced.")] = None,
    keep_raw: Annotated[bool, typer.Option(help="Keep the downloaded files instead of deleting them.")] = False,
    delay: Annotated[float, typer.Option(help="Seconds between two requests to smogon.com.")] = REQUEST_DELAY_S,
) -> None:
    """Download, parse and check whole months, writing data/interim/<month>/*.parquet.

    A month with a file that fails to parse is skipped (its errors are listed, its raw files
    stay cached) and the run moves on to the next month.
    """
    inventory = pl.read_parquet(INVENTORY_PATH)
    todo = months or [m for m in inventory["month"].unique().sort() if not is_synced(m)]
    files = {month: month_files(inventory, month) for month in todo}
    failed: list[MonthFailedError] = []

    columns = [
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("files"),
        TimeElapsedColumn(),
        TextColumn("left:"),
        TimeRemainingColumn(),
    ]
    with SmogonClient(delay_s=delay) as client, Progress(*columns) as progress:
        bar = progress.add_task("", total=sum(f.height for f in files.values()))
        for number, month in enumerate(todo, start=1):
            progress.update(bar, description=f"{month} ({number}/{len(todo)})")
            start = time.monotonic()
            try:
                counts = sync_month(client, files[month], keep_raw=keep_raw, on_file=lambda: progress.advance(bar))
            except MonthFailedError as exc:
                failed.append(exc)
                log = f"data/interim/{month}.errors.txt"
                progress.console.print(f"{month}: FAILED, {len(exc.errors)} file(s), see {log}")
                continue
            progress.console.print(f"{month}: {sum(counts.values()):,} rows in {time.monotonic() - start:.0f}s")

    if failed:
        typer.echo(f"\n{len(failed)} month(s) not written:")
        for failure in failed:
            typer.echo(f"  {failure.month}")
            for error in failure.errors[:5]:
                typer.echo(f"    {error}")
            if len(failure.errors) > 5:
                typer.echo(f"    ... {len(failure.errors) - 5} more in data/interim/{failure.month}.errors.txt")
        raise typer.Exit(1)
