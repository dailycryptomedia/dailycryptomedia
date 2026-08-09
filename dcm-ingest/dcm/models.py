"""Skema basis data.

PENTING — batasan yang disengaja
--------------------------------
Tabel Article tidak memiliki kolom untuk isi artikel penuh, dan itu bukan
kelalaian. Menyimpan lalu menerjemahkan badan artikel milik penerbit lain
adalah penggandaan sekaligus pembuatan karya turunan; keduanya hak eksklusif
pemegang hak cipta. Yang disimpan hanyalya judul, kutipan pendek yang memang
disediakan penerbit di dalam feed, dan tautan kanonis.

Bila suatu saat ada yang hendak menambahkan kolom `body`, hentikan dan
selesaikan dulu perjanjian sindikasinya.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ArticleStatus(StrEnum):
    """Siklus hidup satu item sepanjang pipeline."""

    NEW = "new"                  # baru diambil, belum diproses
    TRANSLATED = "translated"    # judul + ringkasan Indonesia siap
    PUBLISHED = "published"      # tampil di situs
    DUPLICATE = "duplicate"      # kabar yang sama sudah ada dari sumber lain
    SUPPRESSED = "suppressed"    # ditahan: skor rendah, terlalu tua, atau berbayar
    FAILED = "failed"            # pemrosesan gagal, lihat error_note


class Source(Base):
    """Satu penerbit beserta keadaan pollingnya."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    homepage: Mapped[str] = mapped_column(String(512))
    lang: Mapped[str] = mapped_column(String(8), default="en")

    # URL feed yang benar-benar berhasil di-resolve oleh discovery.
    feed_url: Mapped[str | None] = mapped_column(String(512), default=None)

    attribution: Mapped[str] = mapped_column(String(128), default="")
    license_note: Mapped[str] = mapped_column(Text, default="")
    needs_permission: Mapped[bool] = mapped_column(Boolean, default=True)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
    publish: Mapped[bool] = mapped_column(Boolean, default=False)

    # Keadaan permintaan bersyarat. Menghemat bandwidth penerbit dan membuat
    # bot kita tidak mengunduh ulang feed yang tidak berubah.
    etag: Mapped[str | None] = mapped_column(String(256), default=None)
    last_modified: Mapped[str | None] = mapped_column(String(128), default=None)

    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"<Source {self.slug} lang={self.lang}>"


class Article(Base):
    """Satu item berita.

    Kolom bersufiks `_src` berisi teks asli penerbit apa adanya.
    Kolom bersufiks `_id` berisi hasil kerja kita sendiri dalam bahasa
    Indonesia: judul diterjemahkan, ringkasan ditulis ulang.
    """

    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("source_id", "guid", name="uq_article_source_guid"),
        Index("ix_article_published", "published_at"),
        Index("ix_article_status_score", "status", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    source: Mapped[Source] = relationship(back_populates="articles")

    # --- Identitas --------------------------------------------------------
    guid: Mapped[str] = mapped_column(String(512))
    canonical_url: Mapped[str] = mapped_column(String(1024))
    url_hash: Mapped[str] = mapped_column(String(64), index=True)

    # --- Teks asli (kutipan feed saja, bukan isi artikel) -----------------
    title_src: Mapped[str] = mapped_column(Text)
    excerpt_src: Mapped[str] = mapped_column(Text, default="")
    lang_src: Mapped[str] = mapped_column(String(8), default="en")
    author_src: Mapped[str | None] = mapped_column(String(256), default=None)

    # --- Hasil bahasa Indonesia -------------------------------------------
    title_id: Mapped[str | None] = mapped_column(Text, default=None)
    summary_id: Mapped[str | None] = mapped_column(Text, default=None)
    translated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    translate_model: Mapped[str | None] = mapped_column(String(64), default=None)

    # --- Klasifikasi & peringkat ------------------------------------------
    rubric: Mapped[str] = mapped_column(String(32), default="pasar", index=True)
    id_relevance: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)

    # --- Deduplikasi ------------------------------------------------------
    simhash: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    cluster_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    is_cluster_lead: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Metadata ---------------------------------------------------------
    image_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    status: Mapped[str] = mapped_column(String(24), default=ArticleStatus.NEW, index=True)
    error_note: Mapped[str | None] = mapped_column(Text, default=None)

    # --- Bentuk tampilan --------------------------------------------------
    @property
    def display_title(self) -> str:
        """Judul Indonesia bila ada, kalau tidak pakai judul asli."""
        return self.title_id or self.title_src

    @property
    def display_summary(self) -> str:
        return self.summary_id or ""

    def to_card(self) -> dict:
        """Bentuk yang dikonsumsi frontend, cocok dengan DATA.articles.

        Setiap kartu selalu membawa atribusi dan tautan kanonis. Frontend
        tidak boleh menampilkan kartu tanpa keduanya.
        """
        return {
            "id": self.id,
            "k": self.rubric,
            "cat": RUBRIC_LABELS.get(self.rubric, "Pasar"),
            "t": self.display_title,
            "x": self.display_summary,
            "w": self.source.attribution or self.source.name,
            "url": self.canonical_url,
            "img": self.image_url,
            "a": humanize_age(self.published_at),
            "r": estimate_read_time(self.excerpt_src),
            "translated": bool(self.title_id) and self.lang_src != "id",
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


RUBRIC_LABELS: dict[str, str] = {
    "regulasi": "Regulasi",
    "tokenisasi": "Tokenisasi",
    "bitcoin": "Bitcoin",
    "defi": "DeFi",
    "nft": "NFT & Gaming",
    "web3": "Web3",
    "bisnis": "Bisnis",
    "pasar": "Pasar",
}


def humanize_age(dt: datetime | None) -> str:
    """Ubah stempel waktu jadi keterangan relatif berbahasa Indonesia."""
    if dt is None:
        return "baru saja"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = utcnow() - dt
    mins = int(delta.total_seconds() // 60)

    if mins < 1:
        return "baru saja"
    if mins < 60:
        return f"{mins} menit lalu"
    hours = mins // 60
    if hours < 24:
        return f"{hours} jam lalu"
    days = hours // 24
    if days == 1:
        return "kemarin"
    if days < 7:
        return f"{days} hari lalu"
    weeks = days // 7
    return f"{weeks} pekan lalu"


def estimate_read_time(text: str) -> str:
    """Perkiraan kasar waktu baca. Kutipan feed pendek, jadi dibulatkan naik."""
    words = len((text or "").split())
    minutes = max(2, round(words / 200) + 2)
    return f"{minutes} menit"
