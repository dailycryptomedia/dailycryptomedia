"""Ekspor basis data menjadi berkas JSON statis.

Kenapa modul ini ada
--------------------
GitHub Pages hanya menyajikan berkas, bukan proses. Tidak ada FastAPI yang
hidup di sana, jadi tidak ada yang bisa menjawab permintaan ke /api/articles.

Modul ini membalik urutannya: alih-alih menjawab permintaan saat pembaca
datang, kita menuliskan seluruh jawaban lebih dulu sebagai berkas JSON, lalu
GitHub Pages tinggal menyajikannya. Isi berkas dibuat SAMA PERSIS dengan
balasan api.py, sehingga dcm-live.js hanya perlu mengubah alamat yang
dipanggil, bukan cara mengolah datanya.

Peta berkas yang dihasilkan

    data/api/health.json              <- /api/health
    data/api/rubrics.json             <- /api/rubrics
    data/api/articles.json            <- /api/articles
    data/api/articles/top.json        <- /api/articles/top?limit=5
    data/api/articles/<rubrik>.json   <- /api/articles?rubric=<rubrik>

Aturan atribusi yang berlaku di api.py berlaku penuh di sini juga: kartu
dibangun lewat Article.to_card(), jadi setiap kartu tetap membawa nama
penerbit dan tautan kanonis. Hanya artikel dari sumber dengan publish=true
yang ikut diekspor, sehingga sumber yang izin sindikasinya belum turun tidak
pernah bocor ke berkas publik.

Penyeimbangan penerbit
----------------------
Urutan murni berdasarkan skor membuat satu penerbit memborong hampir seluruh
kursi, karena penerbit yang paling produktif otomatis punya paling banyak
kandidat berskor tinggi. Hasilnya situs agregator terlihat seperti cermin
satu media saja. _seimbangkan() menyusun ulang secara bergiliran antar
sumber sebelum dipotong ke batas akhir.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from .models import RUBRIC_LABELS, Article, ArticleStatus, Source
from .pipeline import get_session
from .settings import ROOT

log = logging.getLogger(__name__)

# ROOT menunjuk ke folder dcm-ingest. Induknya adalah akar repo, tempat
# folder docs/ berada. Itulah yang disajikan GitHub Pages.
DEFAULT_OUT = ROOT.parent / "docs" / "data" / "api"

# Berapa kali lipat kandidat yang diambil sebelum penyeimbangan. Kolam yang
# lebih besar memberi ruang bagi sumber yang lebih sepi untuk ikut terpilih.
# Terlalu besar hanya membuang memori tanpa menambah keragaman.
FAKTOR_KOLAM = 5


def _write(path: Path, payload) -> None:
    """Tulis satu berkas JSON.

    indent=1 dipakai dengan sengaja. Berkas ini di-commit ke Git setiap kali
    pipeline jalan; JSON satu baris menghasilkan diff yang tidak terbaca sama
    sekali, sedangkan JSON berindentasi menghasilkan diff per artikel yang
    bisa ditelusuri saat ada yang aneh.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def _base_query(since: datetime):
    """Penyaring dasar: tayang, sumbernya boleh terbit, dan masih baru."""
    return (
        select(Article)
        .options(joinedload(Article.source))
        .join(Source)
        .where(
            Article.status == ArticleStatus.PUBLISHED,
            Source.publish.is_(True),
            Article.fetched_at >= since,
        )
    )


def _seimbangkan(kandidat: list, batas: int) -> list:
    """Susun ulang agar penerbit bergiliran, bukan didominasi satu nama.

    Masukan harus SUDAH terurut berdasarkan skor menurun. Fungsi ini
    mengelompokkan per sumber sambil mempertahankan urutan itu, lalu
    mengambil satu artikel dari tiap sumber secara berputar.

    Sumber yang kandidatnya habis lebih dulu akan terlewati pada putaran
    berikutnya, sehingga sisa kursi tetap terisi penuh oleh sumber yang
    masih punya stok. Dengan begitu keragaman meningkat tanpa mengurangi
    jumlah artikel yang tampil.
    """
    if not kandidat:
        return []

    per_sumber: dict = {}
    urutan: list = []
    for artikel in kandidat:
        sid = artikel.source_id
        if sid not in per_sumber:
            per_sumber[sid] = []
            # Urutan giliran ditentukan oleh skor tertinggi tiap sumber,
            # jadi penerbit dengan berita terkuat tetap mendapat kursi
            # pertama pada setiap putaran.
            urutan.append(sid)
        per_sumber[sid].append(artikel)

    hasil: list = []
    while len(hasil) < batas:
        ada_yang_maju = False
        for sid in urutan:
            antrean = per_sumber[sid]
            if not antrean:
                continue
            hasil.append(antrean.pop(0))
            ada_yang_maju = True
            if len(hasil) >= batas:
                break
        # Semua antrean kosong: kolam kandidat memang lebih kecil dari batas.
        if not ada_yang_maju:
            break

    return hasil


def export_all(
    out_dir: Path | str | None = None,
    limit: int = 60,
    top_limit: int = 5,
    hours: int = 72,
) -> dict:
    """Tulis seluruh berkas JSON. Mengembalikan ringkasan untuk dicetak."""
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)

    written: dict[str, int] = {}

    with get_session() as session:

        # --- Semua artikel -------------------------------------------------
        stmt = _base_query(since).order_by(Article.score.desc())
        total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        kandidat = session.scalars(stmt.limit(limit * FAKTOR_KOLAM)).all()
        articles = _seimbangkan(kandidat, limit)
        cards = [a.to_card() for a in articles]

        _write(out / "articles.json", {
            "total": total,
            "limit": limit,
            "offset": 0,
            "articles": cards,
        })
        written["articles"] = len(cards)

        # --- Sorotan -------------------------------------------------------
        # Blok Sorotan paling terlihat di halaman depan, jadi keragamannya
        # paling penting. Kolam sengaja dibuat lega agar lima kursi itu
        # biasanya terisi lima penerbit berbeda.
        top_since = now - timedelta(hours=24)
        top_kandidat = session.scalars(
            _base_query(top_since)
            .order_by(Article.score.desc())
            .limit(top_limit * FAKTOR_KOLAM * 2)
        ).all()
        top = _seimbangkan(top_kandidat, top_limit)
        # Bila 24 jam terakhir sepi, jatuh kembali ke jendela penuh supaya
        # blok Sorotan tidak pernah kosong di halaman depan.
        if not top:
            top = articles[:top_limit]
            _write(out / "articles" / "top.json", [a for a in cards[:top_limit]])
        else:
            _write(out / "articles" / "top.json", [a.to_card() for a in top])
        written["top"] = len(top)

        # --- Per rubrik ----------------------------------------------------
        # Jendela waktunya harus sama dengan jendela berkas per rubrik. Kalau
        # hitungan memakai seluruh basis data sementara berkasnya hanya 72 jam
        # terakhir, tab bisa menampilkan "Regulasi 4" lalu membuka halaman
        # kosong — dan pembaca menyimpulkan situsnya rusak.
        rows = session.execute(
            select(Article.rubric, func.count(Article.id))
            .join(Source)
            .where(
                Article.status == ArticleStatus.PUBLISHED,
                Source.publish.is_(True),
                Article.fetched_at >= since,
            )
            .group_by(Article.rubric)
        ).all()
        counts = dict(rows)

        rubrics_payload = []
        for key, label in RUBRIC_LABELS.items():
            if counts.get(key, 0) <= 0:
                continue
            rubrics_payload.append({"k": key, "label": label, "jumlah": counts[key]})

            r_stmt = (
                _base_query(since)
                .where(Article.rubric == key)
                .order_by(Article.score.desc())
            )
            r_total = session.scalar(
                select(func.count()).select_from(r_stmt.subquery())
            ) or 0
            r_kandidat = session.scalars(r_stmt.limit(limit * FAKTOR_KOLAM)).all()
            r_articles = _seimbangkan(r_kandidat, limit)

            _write(out / "articles" / f"{key}.json", {
                "total": r_total,
                "limit": limit,
                "offset": 0,
                "articles": [a.to_card() for a in r_articles],
            })
            written[f"rubrik:{key}"] = len(r_articles)

        _write(out / "rubrics.json", rubrics_payload)

        # --- Kesehatan -----------------------------------------------------
        total_all = session.scalar(select(func.count(Article.id))) or 0
        published = session.scalar(
            select(func.count(Article.id)).where(
                Article.status == ArticleStatus.PUBLISHED
            )
        ) or 0

        latest = session.scalar(select(func.max(Article.fetched_at)))
        stale_minutes = None
        if latest:
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            stale_minutes = int((now - latest).total_seconds() // 60)

        failing = list(session.scalars(
            select(Source.slug).where(Source.fail_count > 0, Source.active.is_(True))
        ))

        _write(out / "health.json", {
            # Situs statis: "basi" di sini berarti pipeline GitHub Actions
            # tidak berhasil jalan, bukan bahwa server mati.
            "status": "ok" if stale_minutes is not None and stale_minutes < 120 else "basi",
            "artikel_total": total_all,
            "artikel_tayang": published,
            "menit_sejak_pengambilan_terakhir": stale_minutes,
            "sumber_bermasalah": failing,
            "diekspor_pada": now.isoformat(),
            "mode": "statis",
        })

    log.info("ekspor selesai ke %s", out)
    return {"folder": str(out), **written}
