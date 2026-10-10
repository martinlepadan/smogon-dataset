from datetime import datetime

from smogon_dataset.listing import Entry, parse_listing

LISTING = """<html>
<head><title>Index of /stats/2026-09/</title></head>
<body>
<h1>Index of /stats/2026-09/</h1><hr><pre><a href="../">../</a>
<a href="chaos/">chaos/</a>                                             01-Oct-2026 14:40                   -
<a href="gen1nu-0.txt">gen1nu-0.txt</a>                                       01-Oct-2026 14:40                1802
<a href="gen9monotype-monobug-1630.txt">gen9monotype-monobug-1630.txt</a>  01-Oct-2026 14:40               15591
</pre><hr></body>
</html>"""


def test_parse_listing_skips_parent_link() -> None:
    assert parse_listing(LISTING) == [
        Entry("chaos", is_dir=True, size=None, modified=datetime(2026, 10, 1, 14, 40)),
        Entry("gen1nu-0.txt", is_dir=False, size=1802, modified=datetime(2026, 10, 1, 14, 40)),
        Entry("gen9monotype-monobug-1630.txt", is_dir=False, size=15591, modified=datetime(2026, 10, 1, 14, 40)),
    ]
