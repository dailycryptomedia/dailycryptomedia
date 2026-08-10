"""Orkestrasi pipeline: ambil -> normalkan -> simpan -> dedup -> terjemah -> terbit.

Setiap tahap idempoten. Menjalankan pipeline dua kali berturut-turut tidak
menghasilkan artikel ganda dan tidak memicu terjemahan ulang, karena setiap
tahap menyaring berdasarkan status dan pasangan unik (source_id, guid).

Itu penting karena pipeline berita akan gagal di tengah jalan: feed timeout,
API kehabisan kuota, proses dimatikan saat deploy. Pemulihannya harus
sesederhana menjalankannya lagi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .classify import classify_rubric, compute_score
from .dedupe import DedupeCandidate, cluster
from .feeds import parse_feed
from .http_client import PoliteClient
from .models import Article, ArticleStatus, Base, Source, utcnow
from .settings import get_settings, sources_config

log = logging.getLogger(__name__)

_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, future=True)
    return _engine


def get_session() -> Session:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), future=True, expire_on_commit=False)
    return _SessionFactory()


def init_db() -> None:
    """Buat tabel dan muat sumber dari sources.yaml."""
    Base.metadata.create_all(get_engine())
    sync_sources()


def sync_sources() -> int:
    """Selaraskan tabel sources dengan sources.yaml.

    Field runtime (etag, feed_url yang sudah ditemukan, penghitung kegagalan)
    tidak ditimpa, sehingga menjalankan ulang perintah ini aman.
    """
    config = sources_config()
    changed = 0

    with get_session() as session:
        for spec in config.get("sources", []):
            source = session.scalar(select(Source).where(Source.slug == spec["slug"]))
            if source is None:
                source = Source(slug=spec["slug"])
                session.add(source)
                changed += 1

            source.name = spec["name"]
            source.homepage = spec["homepage"]
            source.lang = spec.get("lang", "en")
            source.attribution = spec.get("attribution", spec["name"])
            source.license_note = spec.get("license_note", "")
            source.needs_permission = spec.get("needs_permission", True)
            source.publish = spec.get("publish", False)
            source.active = spec.get("active", True)

        session.commit()

    log.info("sinkronisasi sumber selesai, %s sumber baru", changed)
    return changed


# =============================================================================
#  TAHAP 1 — PENGAMBILAN
# =============================================================================

async def fetch_all() -> dict[str, int]:
    """Poll semua sumber aktif, simpan item baru.

    Sumber diproses berbarengan tetapi setiap domain tetap dibatasi lajunya
    oleh PoliteClient, jadi keserempakan di sini tidak berubah menjadi
    lonjakan trafik ke satu penerbit.
    """
    config = sources_config()
    defaults = config.get("defaults", {})
    spec_by_slug = {s["slug"]: s for s in config.get("sources", [])}

    with get_session() as session:
        sources = list(session.scalars(select(Source).where(Source.active.is_(True))))

    stats = {"dicoba": 0, "tidak_berubah": 0, "item_baru": 0, "gagal": 0}
    semaphore = asyncio.Semaphore(get_settings().fetch_concurrency)

    async with PoliteClient(
        user_agent=defaults.get("user_agent", "DailyCryptoMediaBot/1.0"),
        timeout=defaults.get("timeout_seconds", 20),
        min_interval=defaults.get("min_interval_seconds", 3.0),
        respect_robots=defaults.get("respect_robots", True),
    ) as client:

        async def handle(source: Source) -> None:
            async with semaphore:
                spec = spec_by_slug.get(source.slug, {})
                stats["dicoba"] += 1

                # Temukan URL feed bila belum diketahui.
                feed_url = source.feed_url
                if not feed_url:
                    feed_url, note = await client.discover_feed(
                        source.homepage, spec.get("feed_candidates", [])
                    )
                    if not feed_url:
                        _record_failure(source.slug, note)
                        stats["gagal"] += 1
                        return
                    log.info("[%s] feed ditemukan lewat %s: %s", source.slug, note, feed_url)

                result = await client.get(feed_url, source.etag, source.last_modified)

                if result.not_modified:
                    stats["tidak_berubah"] += 1
                    _touch_source(source.slug, feed_url, result.etag, result.last_modified)
                    return

                if not result.ok:
                    _record_failure(source.slug, result.error or f"HTTP {result.status}")
                    stats["gagal"] += 1
                    return

                items = parse_feed(result.content, source_lang=source.lang)
                max_items = defaults.get("max_items_per_poll", 40)
                new_count = _persist_items(source.slug, items[:max_items])

                stats["item_baru"] += new_count
                _touch_source(source.slug, feed_url, result.etag, result.last_modified, success=True)
                log.info("[%s] %s item diperiksa, %s baru", source.slug, len(items), new_count)

        await asyncio.gather(*(handle(s) for s in sources), return_exceptions=True)

    return stats


def _touch_source(slug, feed_url, etag, last_modified, success: bool = False) -> None:
    with get_session() as session:
        source = session.scalar(select(Source).where(Source.slug == slug))
        if source is None:
            return
        source.feed_url = feed_url
        source.etag = etag
        source.last_modified = last_modified
        source.last_fetch_at = utcnow()
        if success:
            source.last_success_at = utcnow()
            source.fail_count = 0
            source.last_error = None
        session.commit()


def _record_failure(slug: str, error: str) -> None:
    with get_session() as session:
        source = session.scalar(select(Source).where(Source.slug == slug))
        if source is None:
            return
        source.fail_count += 1
        source.last_error = error[:500]
        source.last_fetch_at = utcnow()
        # Sumber yang gagal sepuluh kali berturut-turut dinonaktifkan supaya
        # tidak terus dihubungi. Aktifkan lagi setelah diperiksa manual.
        if source.fail_count >= 10:
            source.active = False
            log.error("[%s] dinonaktifkan setelah %s kegagalan beruntun", slug, source.fail_count)
        session.commit()
    log.warning("[%s] gagal: %s", slug, error)


def _persist_items(slug: str, items: list) -> int:
    """Simpan item yang belum ada. Mengembalikan jumlah baris baru."""
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.max_article_age_days)
    new_count = 0

    with get_session() as session:
        source = session.scalar(select(Source).where(Source.slug == slug))
        if source is None:
            return 0

        existing = {
            row for row in session.scalars(
                select(Article.guid).where(Article.source_id == source.id)
            )
        }

        for item in items:
            if item.guid in existing:
                continue
            if item.published_at and item.published_at < cutoff:
                continue

            score, relevance = compute_score(
                item.title, item.excerpt, item.published_at, source.lang
            )

            session.add(Article(
                source_id=source.id,
                guid=item.guid,
                canonical_url=item.url,
                url_hash=item.url_hash,
                title_src=item.title,
                excerpt_src=item.excerpt,
                lang_src=item.lang,
                author_src=item.author,
                image_url=item.image_url,
                published_at=item.published_at,
                rubric=classify_rubric(item.title, item.excerpt),
                id_relevance=relevance,
                score=score,
                status=ArticleStatus.NEW,
            ))
            new_count += 1

        session.commit()

    return new_count


# =============================================================================
#  TAHAP 2 — DEDUPLIKASI
# =============================================================================

def deduplicate(window_hours: int = 48) -> int:
    """Kelompokkan artikel yang memberitakan peristiwa sama.

    Hanya artikel dalam jendela waktu tertentu yang dibandingkan. Dua berita
    berjarak seminggu yang judulnya mirip hampir pasti dua peristiwa berbeda.
    """
    threshold = get_settings().dedupe_similarity_threshold
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    marked = 0

    with get_session() as session:
        articles = list(session.scalars(
            select(Article).where(
                Article.status.in_([ArticleStatus.NEW, ArticleStatus.TRANSLATED,
                                     ArticleStatus.PUBLISHED]),
                Article.fetched_at >= since,
            )
        ))
        if not articles:
            return 0

        by_hash = {a.url_hash: a for a in articles}
        candidates = [
            DedupeCandidate(key=a.url_hash, title=a.display_title,
                            score=a.score, lang=a.lang_src)
            for a in articles
        ]

        for key, (cluster_id, is_leader) in cluster(candidates, threshold).items():
            article = by_hash[key]
            article.cluster_id = cluster_id
            article.is_cluster_lead = is_leader
            if not is_leader and article.status != ArticleStatus.DUPLICATE:
                article.status = ArticleStatus.DUPLICATE
                marked += 1

        session.commit()

    log.info("deduplikasi: %s artikel ditandai kembar", marked)
    return marked


# =============================================================================
#  TAHAP 3 — TERJEMAHAN
# =============================================================================

def promote_local() -> int:
    """Siapkan artikel berbahasa Indonesia tanpa memanggil API sama sekali.

    Sumber lokal tidak butuh terjemahan: judulnya dipakai apa adanya dan
    kutipan feed dijadikan ringkasan. Pekerjaan ini dulunya berada di dalam
    kelas Translator, yang menolak berjalan tanpa kunci API — akibatnya empat
    sumber Indonesia ikut terhenti hanya karena kunci Anthropic belum diisi.

    Sekarang berdiri sendiri, sehingga situs tetap terisi berita segar
    walaupun tahap terjemahan dilewati sepenuhnya.
    """
    from .models import ArticleStatus

    with get_session() as session:
        articles = list(session.scalars(
            select(Article).where(
                Article.status == ArticleStatus.NEW,
                Article.lang_src == "id",
                Article.is_cluster_lead.is_(True),
            )
        ))

        for article in articles:
            article.title_id = article.title_src
            article.summary_id = (article.excerpt_src or "")[:220]
            article.translated_at = datetime.now(timezone.utc)
            article.translate_model = "tanpa-terjemahan"
            article.status = ArticleStatus.TRANSLATED

        session.commit()

    log.info("sumber lokal disiapkan: %s artikel", len(articles))
    return len(articles)


def retry_failed(limit: int = 500) -> int:
    """Kembalikan artikel berstatus FAILED ke antrean terjemahan.

    Terjemahan yang gagal karena kunci API salah atau gangguan jaringan
    berakhir sebagai FAILED, dan pipeline tidak pernah mencobanya lagi karena
    hanya mengambil yang berstatus NEW. Perintah ini yang membuka jalannya.
    """
    from .models import ArticleStatus

    with get_session() as session:
        articles = list(session.scalars(
            select(Article)
            .where(Article.status == ArticleStatus.FAILED)
            .order_by(Article.score.desc())
            .limit(limit)
        ))

        for article in articles:
            article.status = ArticleStatus.NEW
            article.error_note = None

        session.commit()

    log.info("dikembalikan ke antrean: %s artikel", len(articles))
    return len(articles)


def translate_pending(limit: int = 60) -> int:
    """Terjemahkan artikel berstatus NEW yang merupakan pemimpin cluster.

    Artikel kembar tidak diterjemahkan sama sekali. Tidak ada gunanya
    membayar terjemahan untuk berita yang tidak akan tampil.
    """
    from .translate import Translator

    with get_session() as session:
        articles = list(session.scalars(
            select(Article)
            .where(
                Article.status == ArticleStatus.NEW,
                Article.is_cluster_lead.is_(True),
            )
            .order_by(Article.score.desc())
            .limit(limit)
        ))
        if not articles:
            log.info("tidak ada artikel yang menunggu terjemahan")
            return 0

        count = Translator().translate_articles(articles)
        session.commit()

    log.info("terjemahan selesai: %s artikel", count)
    return count


# =============================================================================
#  TAHAP 4 — PENERBITAN
# =============================================================================

def publish_ready() -> int:
    """Naikkan artikel yang lolos ambang menjadi PUBLISHED.

    Artikel dari sumber dengan publish=false tetap tersimpan untuk pemantauan
    redaksi, tetapi tidak pernah keluar lewat API publik.
    """
    settings = get_settings()
    published = 0

    with get_session() as session:
        articles = list(session.scalars(
            select(Article)
            .join(Source)
            .where(
                Article.status == ArticleStatus.TRANSLATED,
                Article.is_cluster_lead.is_(True),
                Source.publish.is_(True),
            )
        ))

        for article in articles:
            if article.score < settings.min_publish_score:
                article.status = ArticleStatus.SUPPRESSED
                article.error_note = f"skor {article.score} di bawah ambang"
                continue
            if not article.title_id:
                article.status = ArticleStatus.SUPPRESSED
                article.error_note = "judul Indonesia kosong"
                continue
            article.status = ArticleStatus.PUBLISHED
            published += 1

        session.commit()

    log.info("penerbitan: %s artikel tayang", published)
    return published


# =============================================================================
#  JALANKAN SEMUA
# =============================================================================

def run_once(skip_translate: bool = False) -> dict:
    """Jalankan pipeline penuh sekali. Ini yang dipanggil penjadwal."""
    log.info("=== putaran pipeline dimulai ===")

    fetch_stats = asyncio.run(fetch_all())
    duplicates = deduplicate()
    # Sumber Indonesia disiapkan lebih dulu dan selalu, tanpa syarat apa pun.
    # Mereka tidak memanggil API, jadi tidak ada alasan menahannya.
    local = promote_local()
    translated = 0 if skip_translate else translate_pending()
    published = publish_ready()

    summary = {
        **fetch_stats,
        "kembar": duplicates,
        "lokal": local,
        "diterjemahkan": translated,
        "diterbitkan": published,
    }
    log.info("=== putaran selesai: %s ===", summary)
    return summary
