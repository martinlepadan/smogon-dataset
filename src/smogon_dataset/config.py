from pathlib import Path

# Data sources
BASE_URL = "https://www.smogon.com/stats/"
FIRST_MONTH = "2014-11"

# Months with special data structure
SPECIAL_MONTHS = frozenset(
    {
        "2020-06-DLC1",
        "2020-10-DLC2",
        "2020-11-H1",
        "2020-11-H2",
        "2020-12-H1",
        "2020-12-H2",
        "2023-09-DLC1",
        "2023-12-DLC2",
    }
)

# Subfolders of a month
# moveset/ is not parsed: it holds the same data as chaos/, as text.
SECTIONS = ("", "chaos", "leads", "metagame", "mega", "monotype")

# Network settings
USER_AGENT = "smogon-dataset/0.1 (+https://github.com/martinlepadan/smogon-dataset; contact: martin.lepadanc@gmail.com)"
REQUEST_DELAY_S = 1.0
REQUEST_TIMEOUT_S = 60.0
MAX_RETRIES = 5

# Thresholds
CUTOFFS = (0, 1500, 1630, 1695, 1760, 1825)
STANDARD_CUTOFF = 1630
STANDARD_CUTOFF_OU = 1695


def standard_cutoff(format_id: str) -> int:
    """Threshold to separate lite and complete datasets for a given format"""
    return STANDARD_CUTOFF_OU if format_id.endswith("ou") else STANDARD_CUTOFF


# Local paths
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
COMPLETE_DIR = DATA_DIR / "complete"
LITE_DIR = DATA_DIR / "lite"
