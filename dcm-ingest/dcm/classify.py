"""Klasifikasi rubrik dan pemeringkatan.

Dua pekerjaan terpisah yang kebetulan memakai bahan yang sama:

1. Rubrik. Ke kanal mana artikel ini masuk. Berbasis kata kunci, sengaja
   tidak memakai model, karena aturan bisa dibaca dan diperbaiki redaksi
   tanpa perlu melatih apa pun.

2. Skor. Seberapa tinggi artikel ini layak muncul. Menggabungkan relevansi
   untuk pembaca Indonesia, kesegaran, dan kualitas kutipan.

Bagian relevansi Indonesia adalah alasan utama agregator lokal masuk akal.
Berita "SEC menunda keputusan ETF" penting, tetapi "OJK menerbitkan aturan
kustodi" jauh lebih penting bagi pembaca di Jakarta, dan urutan bawaan
berdasarkan waktu tidak akan pernah menangkap perbedaan itu.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from functools import lru_cache

from .settings import sources_config


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Susun pola pencocokan satu istilah pada batas kata.

    Pencocokan substring polos berbahaya di sini. Istilah pendek seperti "bi"
    (Bank Indonesia) cocok di dalam "Bitcoin", "idr" cocok di dalam "hybrid",
    dan akibatnya setiap berita Bitcoin global ikut terangkat seolah-olah
    berita Indonesia. Batas kata menghilangkan seluruh kelas galat itu.
    """
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def matches_any(text: str, terms: list[str]) -> bool:
    """True bila salah satu istilah muncul sebagai kata utuh di dalam teks."""
    return any(_term_pattern(t).search(text) for t in terms)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify_rubric(title: str, excerpt: str = "") -> str:
    """Tentukan rubrik dari kata kunci pada judul dan kutipan.

    Judul diberi bobot tiga kali lipat: judul memang menyatakan topik,
    sedangkan kutipan sering menyerempet banyak hal sekaligus.
    """
    config = sources_config().get("rubrics", {})
    title_l = (title or "").lower()
    excerpt_l = (excerpt or "").lower()

    best_rubric, best_score = "pasar", 0

    for rubric, spec in config.items():
        score = 0
        for keyword in spec.get("keywords", []):
            pattern = _term_pattern(keyword)
            if pattern.search(title_l):
                score += 3
            elif pattern.search(excerpt_l):
                score += 1
        if score > best_score:
            best_rubric, best_score = rubric, score

    return best_rubric


def indonesia_relevance(title: str, excerpt: str = "") -> int:
    """Skor 0 sampai 100 untuk kedekatan berita dengan pembaca Indonesia."""
    config = sources_config().get("relevance_boost", {})
    weights = config.get("weights", {})
    text = f"{title} {excerpt}".lower()

    score = 0
    if matches_any(text, config.get("indonesia", [])):
        score += weights.get("indonesia", 40)
    if matches_any(text, config.get("regional", [])):
        score += weights.get("regional", 15)

    return min(score, 100)


def recency_score(published_at: datetime | None, halflife_hours: float = 8.0) -> float:
    """Peluruhan eksponensial atas usia berita.

    Berita berumur satu paruh waktu bernilai separuh dari berita baru. Dengan
    paruh waktu 8 jam, kabar kemarin sore masih bisa bersaing bila
    relevansinya tinggi, tetapi tidak akan mengalahkan kabar pagi ini.
    """
    if published_at is None:
        return 30.0
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    age_hours = max(0.0, (_now() - published_at).total_seconds() / 3600)
    return 100.0 * math.exp(-age_hours * math.log(2) / max(halflife_hours, 0.5))


def excerpt_quality(excerpt: str) -> float:
    """Hukum item yang kutipannya terlalu tipis untuk diringkas.

    Feed kadang mengirim item tanpa deskripsi sama sekali. Item begitu tidak
    bisa diringkas dengan jujur, jadi peringkatnya diturunkan.
    """
    length = len(excerpt or "")
    if length < 60:
        return 0.0
    if length < 140:
        return 8.0
    return 15.0


def compute_score(
    title: str,
    excerpt: str,
    published_at: datetime | None,
    source_lang: str = "en",
) -> tuple[float, int]:
    """Hitung skor akhir dan relevansi Indonesia.

    Mengembalikan (skor, relevansi_indonesia).

    Bobot: relevansi Indonesia 40 persen, kesegaran 45 persen, kualitas
    kutipan 15 persen. Sumber lokal mendapat tambahan kecil karena tidak
    melewati terjemahan sehingga risiko salah tafsirnya nol.
    """
    config = sources_config().get("relevance_boost", {})
    halflife = config.get("weights", {}).get("recency_hours_halflife", 8)

    relevance = indonesia_relevance(title, excerpt)
    recency = recency_score(published_at, halflife)
    quality = excerpt_quality(excerpt)

    score = (relevance * 0.40) + (recency * 0.45) + quality
    if source_lang == "id":
        score += 5.0

    return round(min(score, 100.0), 2), relevance
