"""Deduplikasi lintas sumber.

Tujuh sumber memberitakan peristiwa yang sama. Tanpa penanganan, halaman
depan akan berisi lima versi kabar yang sama persis dari lima penerbit.

Pendekatannya dua lapis:

1. SimHash pada judul yang sudah dinormalkan. Murah, dan langsung menangkap
   judul yang nyaris identik.
2. Kemiripan token bagi pasangan yang jarak SimHash-nya berdekatan. Menangkap
   kasus "Bitcoin tembus $120.000" versus "Harga Bitcoin lewati $120.000".

Item yang dianggap kembar tidak dihapus. Item itu ditandai DUPLICATE dan
dikaitkan ke satu cluster, sehingga tampilan bisa menampilkan satu berita
utama dengan keterangan "juga diberitakan oleh" bila diinginkan.

Pemimpin cluster dipilih berdasarkan skor tertinggi, bukan yang tercepat
masuk. Sumber berbahasa Indonesia sedikit diunggulkan karena tidak perlu
melewati terjemahan sama sekali.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

# Kata yang terlalu sering muncul di judul kripto sehingga tidak membedakan
# apa pun. Dibuang sebelum sidik jari dihitung.
STOPWORDS = {
    # Indonesia
    "yang", "dan", "di", "ke", "dari", "untuk", "dengan", "pada", "ini", "itu",
    "akan", "telah", "sudah", "bisa", "dapat", "adalah", "sebagai", "dalam",
    "atas", "usai", "jadi", "para", "lebih", "hingga", "soal", "kata", "kini",
    # Inggris
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been", "has",
    "have", "had", "will", "would", "could", "should", "may", "says", "said",
    "after", "over", "amid", "new", "now", "its", "his", "her", "their",
}


@dataclass
class DedupeCandidate:
    """Bentuk minimal yang dibutuhkan proses deduplikasi."""

    key: str          # pengenal unik, biasanya url_hash
    title: str
    score: float = 0.0
    lang: str = "en"


def tokenize(text: str) -> list[str]:
    """Pecah judul menjadi token bermakna."""
    lowered = re.sub(r"[^\w\s$%.-]", " ", text.lower())
    return [
        tok for tok in lowered.split()
        if len(tok) > 2 and tok not in STOPWORDS
    ]


def simhash(text: str, bits: int = 64) -> int:
    """SimHash 64 bit atas token judul.

    Judul yang mirip menghasilkan nilai yang berdekatan dalam jarak Hamming,
    sehingga kemiripan bisa diperiksa tanpa membandingkan semua pasangan.
    """
    tokens = tokenize(text)
    if not tokens:
        return 0

    vector = [0] * bits
    for token in tokens:
        digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        for i in range(bits):
            vector[i] += 1 if (digest >> i) & 1 else -1

    value = 0
    for i in range(bits):
        if vector[i] > 0:
            value |= 1 << i
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def jaccard(a: str, b: str) -> float:
    """Kemiripan token dua judul, 0 sampai 1."""
    set_a, set_b = set(tokenize(a)), set(tokenize(b))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def cluster_id_for(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def cluster(
    candidates: list[DedupeCandidate],
    similarity_threshold: float = 0.82,
    hamming_threshold: int = 12,
) -> dict[str, tuple[str, bool]]:
    """Kelompokkan kandidat menjadi cluster berita.

    Mengembalikan pemetaan: key -> (cluster_id, apakah_pemimpin_cluster).

    hamming_threshold menyaring pasangan yang layak dibandingkan lebih teliti;
    similarity_threshold yang memutuskan. Angka 12 dari 64 bit terbukti cukup
    longgar untuk menangkap terjemahan judul yang berbeda susunannya, tanpa
    membuat perbandingan membengkak.
    """
    if not candidates:
        return {}

    hashes = {c.key: simhash(c.title) for c in candidates}
    by_key = {c.key: c for c in candidates}

    # Union-find sederhana
    parent: dict[str, str] = {c.key: c.key for c in candidates}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys = list(by_key)
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            if hamming(hashes[key_a], hashes[key_b]) > hamming_threshold:
                continue
            if jaccard(by_key[key_a].title, by_key[key_b].title) >= similarity_threshold:
                union(key_a, key_b)

    groups: dict[str, list[str]] = defaultdict(list)
    for key in keys:
        groups[find(key)].append(key)

    result: dict[str, tuple[str, bool]] = {}
    for root, members in groups.items():
        cid = cluster_id_for(root)
        # Pemimpin: skor tertinggi, sumber berbahasa Indonesia diunggulkan
        # karena tidak perlu diterjemahkan sehingga siap tayang lebih cepat.
        leader = max(
            members,
            key=lambda k: (by_key[k].score + (5 if by_key[k].lang == "id" else 0)),
        )
        for key in members:
            result[key] = (cid, key == leader)

    return result
