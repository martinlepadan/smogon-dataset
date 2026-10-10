from typing import Annotated

import typer

from smogon_dataset import __version__
from smogon_dataset.fetch import SmogonClient
from smogon_dataset.inventory import INVENTORY_PATH, build_inventory

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
    """Crawl the archive listings and write one row per file to data/interim/inventory.parquet."""
    with SmogonClient() as client:
        df = build_inventory(client, months)
        INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(INVENTORY_PATH)
        typer.echo(f"{df.height} files, {df['month'].n_unique()} months, {client.requests_made} requests")
        typer.echo(f"-> {INVENTORY_PATH}")
