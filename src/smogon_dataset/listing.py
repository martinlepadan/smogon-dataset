import re
from dataclasses import dataclass
from datetime import datetime

# One line of an nginx autoindex page:
# <a href="gen9ou-1695.txt">gen9ou-1695.txt</a>          01-Oct-2026 14:40          15591
_ENTRY = re.compile(
    r'<a href="(?P<href>[^"]+)">[^<]*</a>\s+'
    r"(?P<modified>\d{2}-\w{3}-\d{4} \d{2}:\d{2})\s+"
    r"(?P<size>-|\d+)"
)


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int | None  # nginx shows "-" for directories
    modified: datetime


def parse_listing(html: str) -> list[Entry]:
    return [
        Entry(
            name=m["href"].rstrip("/"),
            is_dir=m["href"].endswith("/"),
            size=None if m["size"] == "-" else int(m["size"]),
            modified=datetime.strptime(m["modified"], "%d-%b-%Y %H:%M"),
        )
        for m in _ENTRY.finditer(html)
    ]
