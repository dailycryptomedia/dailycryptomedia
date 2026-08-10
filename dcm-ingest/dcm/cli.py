"""Antarmuka baris perintah.

    python -m dcm.cli init          buat tabel, muat sumber dari YAML
    python -m dcm.cli verify        cek endpoint feed setiap sumber
    python -m dcm.cli fetch         ambil feed saja
    python -m dcm.cli translate     terjemahkan yang tertunda saja
    python -m dcm.cli run           pipeline penuh sekali jalan
    python -m dcm.cli watch         pipeline berulang sesuai jadwal
    python -m dcm.cli status        ringkasan isi basis data
    python -m dcm.cli serve         jalankan API
    python -m dcm.cli export        tulis JSON statis untuk GitHub Pages

Jalankan `verify` lebih dulu sebelum apa pun. Perintah itu memberi tahu
endpoint feed mana yang benar-benar hidup, tanpa menyentuh basis data.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import func, select

from .settings import get_settings, sources_config


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

async def _verify() -> int:
    """Cek setiap sumber, laporkan URL feed yang resolve.

    Tidak menulis apa pun ke basis data. Aman dijalankan kapan saja, dan
    inilah cara tercepat mengetahui sumber mana yang berubah endpoint-nya.
    """
    from .http_client import PoliteClient
    from .feeds import parse_feed

    config = sources_config()
    defaults = config.get("defaults", {})
    sources = config.get("sources", [])

    print(f"\nMemeriksa {len(sources)} sumber\n" + "─" * 78)

    failures = 0
    async with PoliteClient(
        user_agent=defaults.get("user_agent", "DailyCryptoMediaBot/1.0"),
        timeout=defaults.get("timeout_seconds", 20),
        min_interval=defaults.get("min_interval_seconds", 3.0),
        respect_robots=defaults.get("respect_robots", True),
    ) as client:
        for spec in sources:
            slug, lang = spec["slug"], spec.get("lang", "en")
            label = f"{slug:<16} [{lang}]"

            feed_url, note = await client.discover_feed(
                spec["homepage"], spec.get("feed_candidates", [])
            )
            if not feed_url:
                print(f"  ✗  {label}  {note}")
                failures += 1
                continue

            result = await client.get(feed_url)
            items = parse_feed(result.content, lang) if result.ok else []
            newest = items[0].title[:44] + "…" if items else "(kosong)"

            flag = "✓" if items else "!"
            print(f"  {flag}  {label}  {len(items):>3} item  {note}")
            print(f"     {feed_url}")
            print(f"     terbaru: {newest}")
            if not items:
                failures += 1

    print("─" * 78)
    translated = sum(1 for s in sources if s.get("lang") != "id")
    print(f"  {len(sources) - failures}/{len(sources)} sumber siap")
    print(f"  {translated} sumber perlu terjemahan, {len(sources) - translated} sudah berbahasa Indonesia\n")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _status() -> int:
    from .models import Article, ArticleStatus, Source
    from .pipeline import get_session

    with get_session() as session:
        total = session.scalar(select(func.count(Article.id))) or 0
        if total == 0:
            print("\nBasis data kosong. Jalankan: python -m dcm.cli run\n")
            return 0

        print(f"\nTotal artikel: {total}\n" + "─" * 62)

        print("  Berdasarkan status")
        for status, count in session.execute(
            select(Article.status, func.count(Article.id)).group_by(Article.status)
        ).all():
            print(f"    {status:<14} {count:>5}")

        print("\n  Berdasarkan rubrik")
        for rubric, count in session.execute(
            select(Article.rubric, func.count(Article.id))
            .where(Article.status == ArticleStatus.PUBLISHED)
            .group_by(Article.rubric).order_by(func.count(Article.id).desc())
        ).all():
            print(f"    {rubric:<14} {count:>5}")

        print("\n  Berdasarkan sumber")
        for name, lang, count in session.execute(
            select(Source.name, Source.lang, func.count(Article.id))
            .join(Article, isouter=True).group_by(Source.id)
            .order_by(func.count(Article.id).desc())
        ).all():
            print(f"    {name:<24} [{lang}] {count:>5}")

        print("─" * 62 + "\n")
    return 0


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------

def _watch(interval_minutes: int) -> int:
    import time
    from .pipeline import run_once

    log = logging.getLogger("dcm.watch")
    log.info("penjadwal aktif, jeda %s menit. Hentikan dengan Ctrl+C.", interval_minutes)

    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("dihentikan pengguna")
            return 0
        except Exception:  # noqa: BLE001 - penjadwal tidak boleh mati
            log.exception("putaran gagal, mencoba lagi pada jadwal berikutnya")
        try:
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            log.info("dihentikan pengguna")
            return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dcm", description="Pipeline agregasi Daily Crypto Media"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log tingkat debug")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="buat tabel dan muat sumber")
    sub.add_parser("verify", help="cek endpoint feed tanpa menyentuh basis data")
    sub.add_parser("fetch", help="ambil feed saja")
    sub.add_parser("dedupe", help="jalankan deduplikasi saja")
    sub.add_parser("status", help="ringkasan isi basis data")
    sub.add_parser("lokal", help="siapkan artikel Indonesia tanpa API")

    p_retry = sub.add_parser("retry", help="kembalikan artikel gagal ke antrean")
    p_retry.add_argument("--limit", type=int, default=500)

    p_translate = sub.add_parser("translate", help="terjemahkan yang tertunda")
    p_translate.add_argument("--limit", type=int, default=60)

    p_run = sub.add_parser("run", help="pipeline penuh sekali jalan")
    p_run.add_argument("--skip-translate", action="store_true",
                       help="lewati terjemahan, berguna saat menguji tanpa kunci API")

    p_watch = sub.add_parser("watch", help="pipeline berulang")
    p_watch.add_argument("--interval", type=int, default=None, help="jeda dalam menit")

    p_export = sub.add_parser("export", help="tulis JSON statis untuk GitHub Pages")
    p_export.add_argument("--out", default=None,
                          help="folder tujuan, bawaan ../docs/data/api")
    p_export.add_argument("--limit", type=int, default=60,
                          help="artikel maksimum per berkas")
    p_export.add_argument("--hours", type=int, default=72,
                          help="hanya berita dalam N jam terakhir")

    p_serve = sub.add_parser("serve", help="jalankan API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    settings = get_settings()

    if args.command == "verify":
        return asyncio.run(_verify())

    if args.command == "status":
        return _status()

    if args.command == "init":
        from .pipeline import init_db
        init_db()
        print("Basis data siap. Selanjutnya: python -m dcm.cli verify")
        return 0

    if args.command == "fetch":
        from .pipeline import fetch_all, init_db
        init_db()
        print(asyncio.run(fetch_all()))
        return 0

    if args.command == "dedupe":
        from .pipeline import deduplicate
        print(f"{deduplicate()} artikel ditandai kembar")
        return 0

    if args.command == "lokal":
        from .pipeline import promote_local
        print(f"{promote_local()} artikel Indonesia disiapkan")
        return 0

    if args.command == "retry":
        from .pipeline import retry_failed
        print(f"{retry_failed(args.limit)} artikel dikembalikan ke antrean")
        return 0

    if args.command == "translate":
        from .pipeline import translate_pending
        print(f"{translate_pending(args.limit)} artikel diterjemahkan")
        return 0

    if args.command == "run":
        from .pipeline import init_db, run_once
        init_db()
        print(run_once(skip_translate=args.skip_translate))
        return 0

    if args.command == "watch":
        from .pipeline import init_db
        init_db()
        return _watch(args.interval or settings.poll_interval_minutes)

    if args.command == "export":
        from .export import export_all
        report = export_all(out_dir=args.out, limit=args.limit, hours=args.hours)
        folder = report.pop("folder")
        print(f"\nJSON statis ditulis ke: {folder}")
        for key, count in report.items():
            print(f"  {key:<22} {count:>4} artikel")
        print()
        return 0

    if args.command == "serve":
        import uvicorn
        uvicorn.run(
            "dcm.api:app",
            host=args.host or settings.api_host,
            port=args.port or settings.api_port,
            reload=args.reload,
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
