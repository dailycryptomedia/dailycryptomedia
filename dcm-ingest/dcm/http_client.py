"""Klien HTTP yang sopan, plus penemuan URL feed otomatis.

Tiga alasan modul ini ada, alih-alih langsung memakai httpx:

1. robots.txt dipatuhi. Bot yang mengabaikannya cepat diblokir, dan blokir
   itu biasanya permanen di tingkat CDN.
2. Setiap domain dibatasi lajunya secara terpisah. Tujuh sumber yang di-poll
   berbarengan tidak boleh berubah jadi lonjakan trafik.
3. Permintaan bersyarat (ETag / If-Modified-Since). Feed berita jarang
   berubah di antara dua polling; balasan 304 menghemat bandwidth kedua pihak
   dan membuat bot kita terlihat baik di log penerbit.

Penemuan feed sengaja dibuat berjenjang karena URL feed berubah tanpa
pengumuman. Menuliskannya keras di kode berarti pipeline mati diam-diam
suatu hari nanti.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

# Jalur feed yang lazim dipakai, dicoba bila kandidat di sources.yaml gagal.
COMMON_FEED_PATHS = (
    "/feed", "/feed/", "/rss", "/rss/", "/rss.xml", "/feed.xml",
    "/atom.xml", "/index.xml", "/arc/outboundfeeds/rss/",
)

FEED_CONTENT_TYPES = (
    "application/rss+xml", "application/atom+xml", "application/xml",
    "text/xml", "application/rdf+xml",
)


@dataclass
class FetchResult:
    """Hasil satu permintaan HTTP."""

    url: str
    status: int
    content: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    content_type: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.content)

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def looks_like_feed(self) -> bool:
        if any(ct in self.content_type.lower() for ct in FEED_CONTENT_TYPES):
            return True
        head = self.content[:600].lstrip().lower()
        return head.startswith(b"<?xml") or b"<rss" in head or b"<feed" in head


@dataclass
class DomainThrottle:
    """Pembatas laju sederhana per domain."""

    min_interval: float
    last_call: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self) -> None:
        async with self.lock:
            gap = time.monotonic() - self.last_call
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self.last_call = time.monotonic()


class PoliteClient:
    """Pembungkus httpx yang menghormati robots.txt dan membatasi laju.

    Dipakai sebagai async context manager:

        async with PoliteClient(user_agent="...") as client:
            result = await client.get("https://example.com/feed")
    """

    def __init__(
        self,
        user_agent: str,
        timeout: float = 20.0,
        min_interval: float = 3.0,
        respect_robots: bool = True,
        max_redirects: int = 5,
    ) -> None:
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.respect_robots = respect_robots
        self._throttles: dict[str, DomainThrottle] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8",
                "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
            },
        )

    async def __aenter__(self) -> "PoliteClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    # -- robots.txt --------------------------------------------------------

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        host = urlparse(url).netloc
        if host in self._robots:
            return self._robots[host]

        robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
        parser: RobotFileParser | None = None
        try:
            resp = await self._client.get(robots_url)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
        except httpx.HTTPError as exc:
            # robots.txt tak terjangkau bukan alasan untuk berhenti; kita
            # catat lalu lanjut dengan asumsi diizinkan.
            log.debug("robots.txt tidak terbaca untuk %s: %s", host, exc)

        self._robots[host] = parser
        return parser

    async def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = await self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    # -- permintaan --------------------------------------------------------

    def _throttle_for(self, url: str) -> DomainThrottle:
        host = urlparse(url).netloc
        if host not in self._throttles:
            self._throttles[host] = DomainThrottle(self.min_interval)
        return self._throttles[host]

    async def get(
        self,
        url: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        """Ambil satu URL, hormati robots dan batas laju.

        Bila etag atau last_modified diberikan, permintaan dikirim secara
        bersyarat dan server boleh membalas 304.
        """
        if not await self.allowed(url):
            return FetchResult(url=url, status=0, error="dilarang oleh robots.txt")

        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        await self._throttle_for(url).wait()

        try:
            resp = await self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return FetchResult(url=url, status=0, error=f"{type(exc).__name__}: {exc}")

        return FetchResult(
            url=str(resp.url),
            status=resp.status_code,
            content=resp.content if resp.status_code == 200 else b"",
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
            content_type=resp.headers.get("Content-Type", ""),
        )

    # -- penemuan feed -----------------------------------------------------

    async def discover_feed(
        self, homepage: str, candidates: list[str] | None = None
    ) -> tuple[str | None, str]:
        """Cari URL feed yang benar-benar hidup.

        Urutan usaha:
          1. Kandidat dari sources.yaml, dari atas ke bawah.
          2. Tag <link rel="alternate" type="application/rss+xml"> di homepage.
          3. Jalur konvensional seperti /feed dan /rss.xml.

        Mengembalikan (url_feed, catatan). url_feed None berarti semua gagal
        dan sumber perlu ditinjau manual.
        """
        tried: list[str] = []

        # 1. Kandidat eksplisit
        for url in candidates or []:
            tried.append(url)
            result = await self.get(url)
            if result.ok and result.looks_like_feed:
                return result.url, "kandidat dari konfigurasi"

        # 2. Autodiscovery dari HTML homepage
        home = await self.get(homepage)
        if home.ok:
            try:
                tree = HTMLParser(home.content.decode("utf-8", errors="replace"))
                for node in tree.css('link[rel="alternate"]'):
                    ctype = (node.attributes.get("type") or "").lower()
                    href = node.attributes.get("href")
                    if not href or not any(ft in ctype for ft in FEED_CONTENT_TYPES):
                        continue
                    url = urljoin(homepage, href)
                    if url in tried:
                        continue
                    tried.append(url)
                    result = await self.get(url)
                    if result.ok and result.looks_like_feed:
                        return result.url, "autodiscovery dari tag <link>"
            except Exception as exc:  # noqa: BLE001 - parsing HTML asing
                log.debug("gagal mengurai homepage %s: %s", homepage, exc)

        # 3. Jalur konvensional
        base = f"{urlparse(homepage).scheme}://{urlparse(homepage).netloc}"
        for path in COMMON_FEED_PATHS:
            url = urljoin(base, path)
            if url in tried:
                continue
            tried.append(url)
            result = await self.get(url)
            if result.ok and result.looks_like_feed:
                return result.url, "jalur konvensional"

        return None, f"tidak ada feed valid setelah mencoba {len(tried)} URL"
