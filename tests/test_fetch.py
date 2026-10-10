import gzip
from pathlib import Path

import httpx

from smogon_dataset.fetch import SmogonClient

PAYLOAD = b'{"info": {"number of battles": 42}}'


# stream= rather than content=: httpx marks content= responses as already read, which a
# real server response never is.
def _server(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith(".json"):
        body = httpx.ByteStream(gzip.compress(PAYLOAD))
        return httpx.Response(200, stream=body, headers={"Content-Encoding": "gzip"})
    return httpx.Response(200, stream=httpx.ByteStream(b"<pre></pre>"))


def test_gzipped_responses_are_cached_compressed(tmp_path: Path) -> None:
    with SmogonClient(cache_dir=tmp_path, delay_s=0, transport=httpx.MockTransport(_server)) as client:
        assert client.get("2026-09/chaos/gen9ou-1695.json") == PAYLOAD
        assert client.get("2026-09/chaos/gen9ou-1695.json") == PAYLOAD
        assert client.requests_made == 1

    cached = tmp_path / "2026-09/chaos/gen9ou-1695.json.gz"
    assert gzip.decompress(cached.read_bytes()) == PAYLOAD
    assert not (tmp_path / "2026-09/chaos/gen9ou-1695.json").exists()


def test_plain_responses_are_cached_as_is(tmp_path: Path) -> None:
    with SmogonClient(cache_dir=tmp_path, delay_s=0, transport=httpx.MockTransport(_server)) as client:
        assert client.get("2026-09/") == b"<pre></pre>"

    assert (tmp_path / "2026-09/index.html").read_bytes() == b"<pre></pre>"
