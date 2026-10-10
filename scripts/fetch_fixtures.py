"""Copy a few real Smogon files from each era into tests/fixtures/<month>/ to test the pipeline"""

import polars as pl

from smogon_dataset.config import ROOT_DIR
from smogon_dataset.fetch import SmogonClient
from smogon_dataset.inventory import INVENTORY_PATH

FIXTURES_DIR = ROOT_DIR / "tests" / "fixtures"

# (month, format): one small format per era
SAMPLES = [
    ("2014-11", "stabmons"),
    ("2014-12", "monotype-monofairy"),
    ("2017-07", "gen7sketchmons"),
    ("2017-07", "gen7monotype-monodragon"),
    ("2020-07", "gen8nfe"),
    ("2020-07", "gen8monotype-monorock"),
    ("2020-11-H1", "gen8nfe"),
    ("2023-07", "gen9nfe"),
    ("2023-07", "gen9monotype-monorock"),
    ("2026-09", "gen9nfe"),
    ("2026-09", "gen9monotype-monorock"),
    ("2026-09", "gen9nationaldexmonotype-matchup_chart"),
]


def main() -> None:
    inventory = pl.read_parquet(INVENTORY_PATH)
    wanted = pl.DataFrame(SAMPLES, schema=["month", "format"], orient="row")
    files = inventory.join(wanted, on=["month", "format"]).filter(
        pl.col("cutoff") == 0, ~pl.col("section").str.ends_with("moveset")
    )
    missing = wanted.join(files, on=["month", "format"], how="anti")
    if missing.height:
        raise SystemExit(f"Not in the inventory: {missing.rows()}")

    with SmogonClient() as client:
        for month, section, file in files.select("month", "section", "file").iter_rows():
            remote = f"{month}/{section}/{file}" if section else f"{month}/{file}"
            target = FIXTURES_DIR / remote
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(client.get(remote))
        print(f"{files.height} files in {FIXTURES_DIR}, {client.requests_made} requests")


if __name__ == "__main__":
    main()
