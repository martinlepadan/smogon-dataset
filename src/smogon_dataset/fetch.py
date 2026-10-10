import gzip
import time
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from smogon_dataset.config import BASE_URL, MAX_RETRIES, RAW_DIR, REQUEST_DELAY_S, REQUEST_TIMEOUT_S, USER_AGENT


def _is_transient(exc: BaseException) -> bool:
    """
    Return True if the exception is worth retrying
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


class SmogonClient:
    """HTTP client for smogon.com/stats that mirrors every response under `cache_dir`.

    A path already in the cache is never requested again, so re-running a crawl is free.
    Directory listings are stored as `<dir>/index.html`.

    Smogon serves its files gzipped. They are cached exactly as received, with a `.gz`
    suffix, and only decompressed when read: chaos/ is ~48 GB gzipped, ~125 GB as plain JSON.
    """

    def __init__(
        self,
        cache_dir: Path = RAW_DIR,
        delay_s: float = REQUEST_DELAY_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.delay_s = delay_s
        self.requests_made = 0
        self._last_request = 0.0
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> "SmogonClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    def cache_path(self, path: str) -> Path:
        """Where `path` lives in the cache, or would live if it was served uncompressed."""
        return self.cache_dir / (path + "index.html" if path.endswith("/") or not path else path)

    def fetch(self, path: str, refresh: bool = False) -> Path:
        """Make sure `path` is in the cache and return the cached file (maybe a .gz)."""
        plain = self.cache_path(path)
        gzipped = plain.with_name(plain.name + ".gz")
        if not refresh:
            for cached in (gzipped, plain):
                if cached.exists():
                    return cached

        content, is_gzip = self._download(path)
        target = gzipped if is_gzip else plain
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so an interrupted run never leaves a truncated file in the cache.
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(content)
        tmp.replace(target)
        return target

    def get(self, path: str, refresh: bool = False) -> bytes:
        cached = self.fetch(path, refresh=refresh)
        return gzip.decompress(cached.read_bytes()) if cached.suffix == ".gz" else cached.read_bytes()

    @retry(
        retry=retry_if_exception(_is_transient),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, max=60),
        reraise=True,
    )
    def _download(self, path: str) -> tuple[bytes, bool]:
        wait = self._last_request + self.delay_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        self.requests_made += 1

        # iter_raw() skips httpx's automatic decompression: we want the bytes as sent.
        with self._http.stream("GET", path) as response:
            response.raise_for_status()
            content = b"".join(response.iter_raw())
            return content, response.headers.get("content-encoding") == "gzip"
