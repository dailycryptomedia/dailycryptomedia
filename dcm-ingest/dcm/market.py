"""Ambil data pasar nyata dan tulis sebagai JSON statis.

Kenapa modul ini terpisah dari pipeline berita
----------------------------------------------
Berita dan harga punya sifat yang sangat berbeda. Berita boleh telat lima
menit; harga yang salah justru lebih buruk daripada harga yang tidak
ditampilkan. Karena itu modul ini memakai aturan main sendiri:

  - Kalau pengambilan gagal, berkas lama TIDAK ditimpa. Situs menampilkan
    angka terakhir yang diketahui benar, lengkap dengan cap waktunya, alih-alih
    kosong atau nol.
  - Setiap kegagalan dicatat tapi tidak pernah menggagalkan seluruh putaran.
    Berita tetap terbit walaupun bursa sedang tidak bisa dihubungi.

Sumber data
-----------
CoinGecko (api.coingecko.com) untuk harga, kapitalisasi, dan dominasi.
Kunci Demo gratis bersifat opsional; tanpa kunci, API tetap bisa dipakai
dengan batas laju yang lebih ketat. CoinGecko sendiri menyarankan memakai
kunci Demo untuk pemanggilan terjadwal seperti punya kita, dan kunci itu
gratis tanpa kartu kredit.

Alternative.me untuk Indeks Takut & Serakah. Tanpa kunci, tanpa pendaftaran.

Keduanya mensyaratkan atribusi. Nama sumbernya ikut ditulis ke dalam JSON
supaya bisa ditampilkan di halaman.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .settings import ROOT

log = logging.getLogger(__name__)

CG = "https://api.coingecko.com/api/v3"
FNG = "https://api.alternative.me/fng/"
DEFAULT_OUT = ROOT.parent / "docs" / "data" / "api" / "market.json"

# Warna lambang koin. Dipakai untuk lingkaran kecil di kolom Aset.
WARNA = {
    "BTC": "#F7931A", "ETH": "#5B7BE8", "USDT": "#19A08A", "BNB": "#D9A21B",
    "SOL": "#7C5CFF", "XRP": "#3B9CFF", "USDC": "#2775CA", "ADA": "#3468D1",
    "DOGE": "#C2A633", "TON": "#0098EA", "AVAX": "#E84142", "TRX": "#E63C2E",
    "LINK": "#2A5ADA", "DOT": "#E6007A", "MATIC": "#8247E5",
}


def _ambil(client: httpx.Client, url: str, params: dict | None = None):
    """Satu permintaan HTTP. Mengembalikan None bila gagal, tanpa melempar."""
    try:
        r = client.get(url, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as exc:                      # noqa: BLE001
        log.warning("gagal mengambil %s: %s", url, exc)
        return None


def _headers() -> dict:
    kunci = os.environ.get("DCM_COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": kunci} if kunci else {}


def ambil_pasar(jumlah: int = 10) -> dict | None:
    """Kumpulkan seluruh angka pasar. None bila bagian intinya gagal."""
    with httpx.Client(headers=_headers()) as client:

        koin = _ambil(client, f"{CG}/coins/markets", {
            "vs_currency": "idr",
            "order": "market_cap_desc",
            "per_page": jumlah,
            "page": 1,
            "sparkline": "true",
            "price_change_percentage": "24h,7d",
        })

        # Tanpa daftar koin, tidak ada yang layak ditampilkan sama sekali.
        if not koin:
            return None

        global_ = _ambil(client, f"{CG}/global")
        indodax = _ambil(client, f"{CG}/exchanges/indodax")
        fng = _ambil(client, FNG, {"limit": 8})

    triliun = 1_000_000_000_000

    coins = []
    for c in koin:
        simbol = (c.get("symbol") or "").upper()
        harga = c.get("current_price") or 0
        percikan = ((c.get("sparkline_in_7d") or {}).get("price")) or []

        # CoinGecko mengembalikan sparkline_in_7d dalam dolar walaupun
        # vs_currency diminta rupiah. Deretnya diskalakan agar titik
        # terakhirnya sama dengan harga rupiah saat ini, sehingga satuannya
        # konsisten dengan kolom Harga di sebelahnya.
        if percikan and harga and percikan[-1]:
            faktor = harga / percikan[-1]
            percikan = [round(v * faktor) for v in percikan]

        coins.append({
            "n": c.get("name"),
            "s": simbol,
            "c": WARNA.get(simbol, "#3B9CFF"),
            "p": harga,
            "ch24": round(c.get("price_change_percentage_24h_in_currency") or 0, 2),
            "ch7": round(c.get("price_change_percentage_7d_in_currency") or 0, 2),
            "cap": round((c.get("market_cap") or 0) / triliun, 0),
            # Ambil 30 titik merata dari 168 titik mingguan agar grafik
            # kecilnya tidak terlalu padat.
            "spark": percikan[::max(1, len(percikan) // 30)][:30],
        })

    hasil = {
        "coins": coins,
        "diperbarui": datetime.now(timezone.utc).isoformat(),
        "sumber": "CoinGecko",
    }

    if global_ and isinstance(global_.get("data"), dict):
        g = global_["data"]
        dom = g.get("market_cap_percentage") or {}
        hasil["global"] = {
            "cap_t": round((g.get("total_market_cap") or {}).get("idr", 0) / triliun, 0),
            "vol_t": round((g.get("total_volume") or {}).get("idr", 0) / triliun, 0),
            "btc": round(dom.get("btc") or 0, 1),
            "eth": round(dom.get("eth") or 0, 1),
        }

    # Volume bursa lokal: Indodax melaporkan dalam BTC, jadi dikalikan harga
    # BTC dalam rupiah yang baru saja kita ambil di panggilan pertama.
    if indodax and coins:
        harga_btc = next((c["p"] for c in coins if c["s"] == "BTC"), 0)
        vol_btc = indodax.get("trade_volume_24h_btc") or 0
        if harga_btc and vol_btc:
            hasil["lokal"] = {
                "vol_t": round(vol_btc * harga_btc / triliun, 1),
                "nama": indodax.get("name", "Indodax"),
            }

    if fng and isinstance(fng.get("data"), list) and fng["data"]:
        d = fng["data"]

        def nilai(i):
            try:
                return int(d[i]["value"])
            except (IndexError, KeyError, TypeError, ValueError):
                return None

        hasil["fng"] = {
            "kini": nilai(0),
            "label": _label_fng(nilai(0)),
            "kemarin": nilai(1),
            "pekan_lalu": nilai(7),
            "sumber": "Alternative.me",
        }

    return hasil


def _label_fng(nilai: int | None) -> str:
    """Terjemahkan angka indeks ke label Indonesia."""
    if nilai is None:
        return ""
    if nilai <= 24:
        return "SANGAT TAKUT"
    if nilai <= 44:
        return "TAKUT"
    if nilai <= 55:
        return "NETRAL"
    if nilai <= 74:
        return "SERAKAH"
    return "SANGAT SERAKAH"


def export_market(out: Path | str | None = None) -> dict:
    """Tulis market.json. Berkas lama dipertahankan bila pengambilan gagal."""
    tujuan = Path(out) if out else DEFAULT_OUT
    data = ambil_pasar()

    if data is None:
        if tujuan.exists():
            log.warning("pengambilan gagal; berkas pasar lama dipertahankan")
            return {"status": "gagal-pakai-lama"}
        log.warning("pengambilan gagal dan belum ada berkas lama")
        return {"status": "gagal-tanpa-data"}

    tujuan.parent.mkdir(parents=True, exist_ok=True)
    with tujuan.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    log.info("pasar diperbarui: %s koin", len(data["coins"]))
    return {
        "status": "ok",
        "koin": len(data["coins"]),
        "global": "global" in data,
        "lokal": "lokal" in data,
        "fng": "fng" in data,
    }
