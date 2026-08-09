"""Pengurai feed: dari RSS/Atom mentah menjadi satu skema seragam.

Tujuh penerbit berarti tujuh dialek RSS. Ada yang memakai <content:encoded>,
ada yang <description>, ada yang menaruh gambar di <media:thumbnail>, di
<enclosure>, atau menyelipkannya sebagai <img> pertama di dalam deskripsi.
Modul ini meratakan semuanya menjadi satu bentuk RawItem.

Batas kutipan ditegakkan di sini, bukan di lapisan tampilan. Feed kadang
mengirim isi artikel penuh; kita potong sebelum menyentuh basis data supaya
teks penuh tidak pernah ikut tersimpan.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

# Kutipan yang disimpan tidak boleh lebih panjang dari ini. Cukup untuk
# meringkas, jauh dari batas yang bisa menggantikan artikel aslinya.
MAX_EXCERPT_CHARS = 400

# Parameter pelacakan yang harus dibuang saat menyusun URL kanonis, supaya
# satu artikel yang sama tidak dianggap dua item berbeda.
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "__twitter_impression", "amp",
}


@dataclass
class RawItem:
    """Satu item feed yang sudah dinormalkan, belum masuk basis data."""

    guid: str
    url: str
    url_hash: str
    title: str
    excerpt: str
    author: str | None
    image_url: str | None
    published_at: datetime | None
    lang: str


def canonicalize_url(url: str) -> str:
    """Buang parameter pelacakan dan fragmen, samakan bentuk penulisan."""
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return url.strip()

    query = "&".join(
        seg for seg in parts.query.split("&")
        if seg and seg.split("=", 1)[0].lower() not in TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunparse((
        parts.scheme.lower(), parts.netloc.lower(), path, parts.params, query, "",
    ))


def hash_url(url: str) -> str:
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()[:32]


def strip_html(raw: str) -> str:
    """Ubah HTML jadi teks polos, rapatkan spasi berlebih."""
    if not raw:
        return ""
    try:
        text = HTMLParser(raw).text(separator=" ")
    except Exception:  # noqa: BLE001 - markup feed sering rusak
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text).strip()


def truncate_excerpt(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    """Potong di batas kalimat bila memungkinkan, kalau tidak di batas kata."""
    text = text.strip()
    if len(text) <= limit:
        return text

    window = text[:limit]
    for stop in (". ", "! ", "? "):
        idx = window.rfind(stop)
        if idx > limit * 0.5:
            return window[: idx + 1].strip()

    idx = window.rfind(" ")
    return (window[:idx] if idx > 0 else window).strip() + "…"


def _parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _extract_image(entry) -> str | None:
    """Gambar bisa muncul di banyak tempat; coba yang paling andal dulu.

    Catatan hak cipta: URL gambar hanya disimpan sebagai rujukan. Jangan
    mengunduh ulang dan menyajikannya dari server sendiri tanpa izin. Bila
    ragu, biarkan kosong dan pakai placeholder milik Daily Crypto Media.
    """
    media = getattr(entry, "media_thumbnail", None) or getattr(entry, "media_content", None)
    if media:
        url = media[0].get("url")
        if url:
            return url

    for link in getattr(entry, "links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return link.get("href")

    body = ""
    if getattr(entry, "content", None):
        body = entry.content[0].get("value", "")
    body = body or getattr(entry, "summary", "")
    if body:
        try:
            node = HTMLParser(body).css_first("img")
            if node:
                return node.attributes.get("src")
        except Exception:  # noqa: BLE001
            pass
    return None


def _extract_excerpt(entry) -> str:
    """Ambil deskripsi terpendek yang masih bermakna.

    Sebagian feed mengirim artikel penuh di <content:encoded>. Kita justru
    lebih suka <summary> yang pendek; kalaupun terpaksa memakai content,
    hasilnya tetap dipotong ke MAX_EXCERPT_CHARS.
    """
    summary = strip_html(getattr(entry, "summary", "") or "")
    if 40 <= len(summary) <= MAX_EXCERPT_CHARS * 2:
        return truncate_excerpt(summary)

    if getattr(entry, "content", None):
        content = strip_html(entry.content[0].get("value", ""))
        if content:
            return truncate_excerpt(content)

    return truncate_excerpt(summary) if summary else ""


def parse_feed(content: bytes, source_lang: str = "en") -> list[RawItem]:
    """Ubah isi feed mentah menjadi daftar RawItem.

    Item tanpa judul atau tanpa tautan dilewati diam-diam: keduanya wajib,
    dan feed yang cacat tidak boleh menghentikan polling sumber lain.
    """
    parsed = feedparser.parse(content)
    if getattr(parsed, "bozo", False):
        log.debug("feed tidak sepenuhnya valid: %s", getattr(parsed, "bozo_exception", ""))

    feed_lang = (getattr(parsed.feed, "language", "") or source_lang).lower()
    lang = "id" if feed_lang.startswith("id") else ("en" if feed_lang.startswith("en") else source_lang)

    items: list[RawItem] = []
    for entry in parsed.entries:
        title = strip_html(getattr(entry, "title", "") or "")
        url = (getattr(entry, "link", "") or "").strip()
        if not title or not url:
            continue

        canonical = canonicalize_url(url)
        author = getattr(entry, "author", None)

        items.append(RawItem(
            guid=str(getattr(entry, "id", "") or canonical),
            url=canonical,
            url_hash=hash_url(canonical),
            title=title[:500],
            excerpt=_extract_excerpt(entry),
            author=(author or None) if isinstance(author, str) else None,
            image_url=_extract_image(entry),
            published_at=_parse_date(entry),
            lang=lang,
        ))

    return items
