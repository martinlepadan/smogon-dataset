import typer

from smogon_dataset import __version__

app = typer.Typer(help="Smogon usage stats pipeline.", no_args_is_help=True)


@app.callback()
def main() -> None:
    pass


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)
