"""Pengujian untuk bagian yang paling mungkin rusak diam-diam.

Prioritas pengujian di sini bukan cakupan baris, melainkan tiga hal yang
kalau gagal tidak akan terlihat sampai terlambat:

  1. Batas kutipan. Bila ini bocor, isi artikel penuh masuk basis data.
  2. Deduplikasi. Bila ini gagal, halaman depan berisi lima berita kembar.
  3. Kanonisasi URL. Bila ini gagal, satu artikel tersimpan berkali-kali.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dcm.dedupe import DedupeCandidate, cluster, jaccard, simhash, tokenize
from dcm.feeds import (
    MAX_EXCERPT_CHARS, canonicalize_url, hash_url, parse_feed, strip_html,
    truncate_excerpt,
)
from dcm.models import estimate_read_time, humanize_age


# ===========================================================================
#  URL
# ===========================================================================

class TestCanonicalUrl:

    def test_parameter_pelacakan_dibuang(self):
        url = "https://decrypt.co/news/artikel?utm_source=twitter&utm_medium=social"
        assert canonicalize_url(url) == "https://decrypt.co/news/artikel"

    def test_parameter_asli_dipertahankan(self):
        url = "https://theblock.co/post?id=123&utm_campaign=x"
        assert canonicalize_url(url) == "https://theblock.co/post?id=123"

    def test_garis_miring_dan_huruf_besar_diseragamkan(self):
        a = canonicalize_url("https://Cointelegraph.com/news/Judul/")
        b = canonicalize_url("https://cointelegraph.com/news/Judul")
        assert a == b

    def test_fragmen_dibuang(self):
        assert "#" not in canonicalize_url("https://x.co/a#bagian")

    def test_url_setara_menghasilkan_hash_sama(self):
        a = "https://coinvestasi.com/berita/x?utm_source=fb"
        b = "https://coinvestasi.com/berita/x/"
        assert hash_url(a) == hash_url(b)


# ===========================================================================
#  KUTIPAN — batas hak cipta ditegakkan di sini
# ===========================================================================

class TestExcerpt:

    def test_kutipan_tidak_pernah_melebihi_batas(self):
        panjang = "Kalimat berita yang cukup panjang. " * 200
        hasil = truncate_excerpt(panjang)
        assert len(hasil) <= MAX_EXCERPT_CHARS + 1

    def test_dipotong_di_batas_kalimat(self):
        teks = "Kalimat pertama. " + ("kata " * 200)
        assert truncate_excerpt(teks).endswith((".", "…"))

    def test_teks_pendek_tidak_diubah(self):
        assert truncate_excerpt("Pendek saja.") == "Pendek saja."

    def test_html_dibersihkan(self):
        html = '<p>Harga <strong>Bitcoin</strong> naik.</p><script>x()</script>'
        hasil = strip_html(html)
        assert "<" not in hasil and "Bitcoin" in hasil

    def test_spasi_berlebih_dirapatkan(self):
        assert strip_html("<p>a</p>\n\n   <p>b</p>") == "a b"


# ===========================================================================
#  PENGURAIAN FEED
# ===========================================================================

RSS_CONTOH = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Contoh</title><language>en-US</language>
  <item>
    <title>Bitcoin tops $120,000 as ETF inflows accelerate</title>
    <link>https://example.com/berita/btc-120k?utm_source=rss</link>
    <guid>https://example.com/berita/btc-120k</guid>
    <description><![CDATA[<p>Bitcoin climbed past the level on Tuesday.</p>]]></description>
    <pubDate>Wed, 06 Aug 2026 09:00:00 GMT</pubDate>
    <author>redaksi@example.com</author>
  </item>
  <item>
    <title>Tanpa tautan</title>
    <description>Item ini harus dilewati.</description>
  </item>
</channel></rss>"""


class TestParseFeed:

    def test_item_valid_terbaca(self):
        items = parse_feed(RSS_CONTOH)
        assert len(items) == 1               # item tanpa tautan dilewati

    def test_url_dikanonisasi_saat_diurai(self):
        item = parse_feed(RSS_CONTOH)[0]
        assert "utm_source" not in item.url

    def test_html_dibuang_dari_kutipan(self):
        item = parse_feed(RSS_CONTOH)[0]
        assert "<p>" not in item.excerpt and "climbed" in item.excerpt

    def test_bahasa_terdeteksi(self):
        assert parse_feed(RSS_CONTOH)[0].lang == "en"

    def test_tanggal_terbit_terbaca(self):
        item = parse_feed(RSS_CONTOH)[0]
        assert item.published_at is not None
        assert item.published_at.year == 2026

    def test_feed_rusak_tidak_melempar_galat(self):
        assert parse_feed(b"bukan xml sama sekali") == []


# ===========================================================================
#  DEDUPLIKASI
# ===========================================================================

class TestDedupe:

    def test_stopword_dibuang(self):
        assert "yang" not in tokenize("Berita yang penting dan menarik")

    def test_judul_identik_berhash_sama(self):
        judul = "Bitcoin tembus level tertinggi baru"
        assert simhash(judul) == simhash(judul)

    def test_judul_mirip_berkemiripan_tinggi(self):
        a = "Bitcoin tembus $120.000 setelah aliran dana ETF meningkat"
        b = "Bitcoin lewati $120.000 usai aliran dana ETF meningkat"
        assert jaccard(a, b) > 0.5

    def test_judul_berbeda_berkemiripan_rendah(self):
        a = "Bitcoin tembus rekor tertinggi baru"
        b = "OJK terbitkan aturan kustodi aset digital"
        assert jaccard(a, b) < 0.2

    def test_berita_kembar_masuk_satu_cluster(self):
        kandidat = [
            DedupeCandidate("a", "Bitcoin tembus level 120.000 dolar hari ini", 50, "en"),
            DedupeCandidate("b", "Bitcoin tembus level 120.000 dolar hari ini", 60, "id"),
            DedupeCandidate("c", "OJK terbitkan aturan kustodi aset digital", 70, "id"),
        ]
        hasil = cluster(kandidat, similarity_threshold=0.75)
        assert hasil["a"][0] == hasil["b"][0]      # kembar
        assert hasil["c"][0] != hasil["a"][0]      # berita lain

    def test_satu_pemimpin_per_cluster(self):
        kandidat = [
            DedupeCandidate("a", "Judul berita yang sama persis di sini", 50, "en"),
            DedupeCandidate("b", "Judul berita yang sama persis di sini", 90, "en"),
        ]
        hasil = cluster(kandidat, similarity_threshold=0.75)
        assert sum(1 for _, lead in hasil.values() if lead) == 1
        assert hasil["b"][1] is True               # skor tertinggi memimpin

    def test_sumber_indonesia_diunggulkan_saat_skor_setara(self):
        kandidat = [
            DedupeCandidate("en", "Berita yang sama persis tentang regulasi", 50, "en"),
            DedupeCandidate("id", "Berita yang sama persis tentang regulasi", 50, "id"),
        ]
        hasil = cluster(kandidat, similarity_threshold=0.75)
        assert hasil["id"][1] is True

    def test_daftar_kosong_aman(self):
        assert cluster([]) == {}


# ===========================================================================
#  TAMPILAN
# ===========================================================================

class TestDisplay:

    @pytest.mark.parametrize("menit,diharapkan", [
        (0, "baru saja"), (5, "5 menit lalu"), (90, "1 jam lalu"),
        (60 * 25, "kemarin"), (60 * 24 * 3, "3 hari lalu"),
    ])
    def test_umur_dalam_bahasa_indonesia(self, menit, diharapkan):
        dt = datetime.now(timezone.utc) - timedelta(minutes=menit)
        assert humanize_age(dt) == diharapkan

    def test_umur_kosong_ditangani(self):
        assert humanize_age(None) == "baru saja"

    def test_waktu_baca_minimal_dua_menit(self):
        assert estimate_read_time("") == "2 menit"


# ===========================================================================
#  SKOR
# ===========================================================================

class TestScoring:
    """Diuji terpisah karena bergantung pada YAML konfigurasi."""

    def test_berita_indonesia_mengungguli_berita_global(self):
        from dcm.classify import compute_score
        sekarang = datetime.now(timezone.utc)
        lokal, _ = compute_score("OJK terbitkan aturan baru", "Regulator Indonesia", sekarang, "id")
        global_, _ = compute_score("SEC delays decision", "US regulator", sekarang, "en")
        assert lokal > global_

    def test_berita_lama_kalah_dari_berita_baru(self):
        from dcm.classify import compute_score
        sekarang = datetime.now(timezone.utc)
        baru, _ = compute_score("Judul sama", "Kutipan sama yang cukup panjang untuk dinilai", sekarang, "en")
        lama, _ = compute_score("Judul sama", "Kutipan sama yang cukup panjang untuk dinilai",
                                sekarang - timedelta(hours=48), "en")
        assert baru > lama

    def test_rubrik_regulasi_terdeteksi(self):
        from dcm.classify import classify_rubric
        assert classify_rubric("OJK terbitkan peraturan baru soal kustodi") == "regulasi"

    def test_rubrik_bitcoin_terdeteksi(self):
        from dcm.classify import classify_rubric
        assert classify_rubric("Bitcoin halving mendorong hashrate naik") == "bitcoin"


# ===========================================================================
#  REGRESI — galat yang pernah terjadi dan tidak boleh terulang
# ===========================================================================

class TestRegresiPencocokanIstilah:
    """Pencocokan substring pernah membuat setiap berita Bitcoin dinilai
    sebagai berita Indonesia, karena "bi" (Bank Indonesia) cocok di dalam
    kata "Bitcoin". Pencocokan kini memakai batas kata.
    """

    def test_bi_tidak_cocok_di_dalam_bitcoin(self):
        from dcm.classify import indonesia_relevance
        assert indonesia_relevance("Bitcoin tops $120,000 as ETF inflows rise") == 0

    def test_bi_tetap_cocok_sebagai_kata_utuh(self):
        from dcm.classify import indonesia_relevance
        assert indonesia_relevance("BI kaji stablecoin rupiah") > 0

    def test_idr_tidak_cocok_di_dalam_kata_lain(self):
        from dcm.classify import indonesia_relevance
        assert indonesia_relevance("Hybrid custody model launched") == 0

    def test_idx_tetap_cocok_sebagai_kata_utuh(self):
        from dcm.classify import indonesia_relevance
        assert indonesia_relevance("IDX siapkan papan pemantauan khusus") > 0

    def test_berita_regional_dapat_nilai_lebih_kecil(self):
        from dcm.classify import indonesia_relevance
        lokal = indonesia_relevance("OJK terbitkan aturan baru")
        regional = indonesia_relevance("Singapore expands tokenisation pilot")
        assert lokal > regional > 0


class TestRegresiRubrik:
    """Kata "bursa" pernah ada di rubrik bisnis, sehingga berita volume
    perdagangan tersedot ke sana alih-alih ke rubrik pasar.
    """

    def test_berita_volume_masuk_rubrik_pasar(self):
        from dcm.classify import classify_rubric
        assert classify_rubric("Volume perdagangan kripto di bursa lokal naik 18 persen") == "pasar"

    def test_berita_pendanaan_tetap_rubrik_bisnis(self):
        from dcm.classify import classify_rubric
        assert classify_rubric("Startup kripto raih pendanaan seri A") == "bisnis"
