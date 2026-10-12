from pathlib import Path

BASE_URL = "https://www.smogon.com/stats/"

# Network settings
USER_AGENT = "smogon-dataset/0.1 (+https://github.com/martinlepadan/smogon-dataset; contact: martin.lepadanc@gmail.com)"
REQUEST_DELAY_S = 1.0
REQUEST_TIMEOUT_S = 60.0
MAX_RETRIES = 5

# Local paths
ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
COMPLETE_DIR = DATA_DIR / "complete"
LITE_DIR = DATA_DIR / "lite"
