"""API JSON yang dikonsumsi frontend Daily Crypto Media.

Bentuk keluaran /api/articles sengaja dibuat sama persis dengan larik
DATA.articles pada index.html, sehingga frontend statis bisa beralih ke data
langsung tanpa mengubah satu pun fungsi render.

Setiap kartu selalu membawa `w` (atribusi penerbit) dan `url` (tautan
kanonis). Keduanya tidak opsional. Frontend tidak boleh menampilkan kartu
tanpa nama sumber dan tautan ke artikel aslinya.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .models import RUBRIC_LABELS, Article, ArticleStatus, Source
from .pipeline import get_session
from .settings import get_settings

settings = get_settings()

app = FastAPI(
    title="Daily Crypto Media — API Agregasi",
    version="1.0.0",
    description=(
        "Menyajikan judul, ringkasan, dan tautan kanonis dari tujuh media "
        "kripto mitra. Isi artikel penuh tidak disimpan maupun disajikan."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def db() -> Session:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@app.get("/api/health")
def health(session: Session = Depends(db)) -> dict:
    """Kesehatan pipeline. Pantau endpoint ini, bukan sekadar proses hidup."""
    total = session.scalar(select(func.count(Article.id))) or 0
    published = session.scalar(
        select(func.count(Article.id)).where(Article.status == ArticleStatus.PUBLISHED)
    ) or 0

    latest = session.scalar(select(func.max(Article.fetched_at)))
    stale_minutes = None
    if latest:
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        stale_minutes = int((datetime.now(timezone.utc) - latest).total_seconds() // 60)

    failing = list(session.scalars(
        select(Source.slug).where(Source.fail_count > 0, Source.active.is_(True))
    ))

    return {
        "status": "ok" if stale_minutes is not None and stale_minutes < 60 else "basi",
        "artikel_total": total,
        "artikel_tayang": published,
        "menit_sejak_pengambilan_terakhir": stale_minutes,
        "sumber_bermasalah": failing,
    }


@app.get("/api/sources")
def list_sources(session: Session = Depends(db)) -> list[dict]:
    """Daftar sumber beserta keadaannya. Dipakai halaman kredit dan pemantauan."""
    sources = session.scalars(select(Source).order_by(Source.name)).all()
    return [
        {
            "slug": s.slug,
            "nama": s.name,
            "homepage": s.homepage,
            "bahasa": s.lang,
            "feed": s.feed_url,
            "tayang": s.publish,
            "perlu_izin": s.needs_permission,
            "aktif": s.active,
            "gagal_beruntun": s.fail_count,
            "terakhir_berhasil": s.last_success_at.isoformat() if s.last_success_at else None,
        }
        for s in sources
    ]


@app.get("/api/articles")
def list_articles(
    session: Session = Depends(db),
    rubric: str | None = Query(None, description="Saring per rubrik, misal 'regulasi'"),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    hours: int = Query(72, ge=1, le=720, description="Hanya berita dalam N jam terakhir"),
    order: str = Query("skor", pattern="^(skor|waktu)$"),
) -> dict:
    """Artikel siap tayang, dalam bentuk yang langsung dipakai frontend."""
    if rubric and rubric not in RUBRIC_LABELS:
        raise HTTPException(400, f"Rubrik tidak dikenal: {rubric}")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(Article)
        .options(joinedload(Article.source))
        .join(Source)
        .where(
            Article.status == ArticleStatus.PUBLISHED,
            Source.publish.is_(True),
            Article.fetched_at >= since,
        )
    )
    if rubric:
        stmt = stmt.where(Article.rubric == rubric)

    stmt = stmt.order_by(
        Article.published_at.desc() if order == "waktu" else Article.score.desc()
    )

    total = session.scalar(
        select(func.count()).select_from(stmt.subquery())
    ) or 0

    articles = session.scalars(stmt.limit(limit).offset(offset)).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "articles": [a.to_card() for a in articles],
    }


@app.get("/api/articles/top")
def top_articles(
    session: Session = Depends(db),
    limit: int = Query(5, ge=1, le=10),
) -> list[dict]:
    """Berita berperingkat untuk blok Sorotan di beranda."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    articles = session.scalars(
        select(Article)
        .options(joinedload(Article.source))
        .join(Source)
        .where(
            Article.status == ArticleStatus.PUBLISHED,
            Source.publish.is_(True),
            Article.fetched_at >= since,
        )
        .order_by(Article.score.desc())
        .limit(limit)
    ).all()
    return [a.to_card() for a in articles]


@app.get("/api/rubrics")
def list_rubrics(session: Session = Depends(db)) -> list[dict]:
    """Rubrik beserta jumlah artikel tayang, untuk membangun tab penyaring."""
    rows = session.execute(
        select(Article.rubric, func.count(Article.id))
        .join(Source)
        .where(Article.status == ArticleStatus.PUBLISHED, Source.publish.is_(True))
        .group_by(Article.rubric)
    ).all()

    counts = dict(rows)
    return [
        {"k": key, "label": label, "jumlah": counts.get(key, 0)}
        for key, label in RUBRIC_LABELS.items()
        if counts.get(key, 0) > 0
    ]
