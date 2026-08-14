"""Penyedia terjemahan alternatif memakai Gemini API.

Modul ini TIDAK menduplikasi logika penerjemahan. Ia menurunkan kelas
``Translator`` dari ``translate.py`` dan hanya mengganti satu hal: cara
permintaan dikirim ke model. Glosarium, prompt sistem, pembentukan pesan,
pengurai balasan, dan ``translate_articles`` semuanya dipakai ulang apa adanya.

Konsekuensinya: setiap perbaikan pada glosarium atau aturan gaya di
``translate.py`` otomatis ikut berlaku di sini. Tidak ada dua tempat yang
harus disamakan secara manual.

Tidak butuh install paket apa pun — hanya modul bawaan Python.

Pengaturan di .env (perhatikan awalan DCM_, mengikuti pola settings.py):

    DCM_TRANSLATE_PROVIDER=gemini
    DCM_GEMINI_API_KEY=isi_kunci_anda
    DCM_GEMINI_MODEL=gemini-2.5-flash-lite    (opsional)
    DCM_GEMINI_RPM=10                          (opsional, jeda antar permintaan)

Uji cepat dari folder dcm-ingest:

    python -m dcm.translate_gemini
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from .settings import get_settings
from .translate import SYSTEM_PROMPT, TranslationResult, Translator, _build_glossary_block

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _env(nama: str, bawaan: str = "") -> str:
    """Baca DCM_<nama>, jatuh ke <nama> polos kalau tidak ada.

    Settings memakai awalan DCM_, tetapi variabel tanpa awalan tetap
    diterima supaya secret GitHub yang sudah terlanjur dibuat tidak
    perlu diganti namanya.
    """
    return (os.getenv(f"DCM_{nama}") or os.getenv(nama) or bawaan).strip()


class GeminiTranslator(Translator):
    """Translator yang memakai Gemini sebagai mesin, bukan Claude.

    Antarmukanya identik dengan kelas induk, jadi pemanggil tidak perlu tahu
    penyedia mana yang sedang dipakai.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        # Sengaja TIDAK memanggil super().__init__(): konstruktor induk
        # membuat klien Anthropic dan menolak jalan tanpa kunci Anthropic.
        settings = get_settings()

        key = api_key or _env("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "DCM_GEMINI_API_KEY belum diisi. Tambahkan barisnya di .env, "
                "atau daftarkan sebagai secret di GitHub untuk workflow."
            )
        self.api_key = key
        self.model = model or _env("GEMINI_MODEL", "gemini-2.5-flash-lite")

        # Kuota harian free tier terbatas, jadi kelompok dibuat lebih besar
        # daripada bawaan: lebih banyak artikel per permintaan berarti lebih
        # sedikit permintaan per hari.
        self.batch_size = max(settings.translate_batch_size, 10)
        self.max_retries = settings.translate_max_retries
        self._glossary_block = _build_glossary_block()

        try:
            rpm = float(_env("GEMINI_RPM", "10"))
        except ValueError:
            rpm = 10.0
        self._jeda = 60.0 / rpm if rpm > 0 else 0.0
        self._panggilan_terakhir = 0.0

    # -- pengendali laju ---------------------------------------------------

    def _tahan_laju(self) -> None:
        """Beri jeda agar batas permintaan per menit tidak terlampaui."""
        selisih = time.time() - self._panggilan_terakhir
        if selisih < self._jeda:
            time.sleep(self._jeda - selisih)
        self._panggilan_terakhir = time.time()

    # -- panggilan api -----------------------------------------------------

    def _kirim(self, pesan_pengguna: str) -> str:
        """Kirim satu permintaan ke Gemini, kembalikan teks balasan."""
        badan = json.dumps({
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": pesan_pengguna}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 4000,
                "responseMimeType": "application/json",
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{BASE_URL}/{self.model}:generateContent",
            data=badan,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        self._tahan_laju()
        with urllib.request.urlopen(req, timeout=120) as resp:
            hasil = json.loads(resp.read().decode("utf-8"))

        kandidat = hasil.get("candidates") or []
        if not kandidat:
            # Biasanya terjadi kalau seluruh permintaan diblokir filter Google.
            raise ValueError(f"tidak ada kandidat pada balasan: {str(hasil)[:200]}")

        bagian = kandidat[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in bagian)

    # -- api publik --------------------------------------------------------

    def translate_batch(self, items: list[tuple[str, str]]) -> list[TranslationResult]:
        """Terjemahkan satu kelompok. items: daftar (judul, kutipan).

        Bentuk keluaran sama persis dengan kelas induk, termasuk penanda
        gagal untuk item yang tidak dikembalikan model.
        """
        if not items:
            return []

        galat_terakhir = ""
        tunggu = 2.0

        for percobaan in range(1, self.max_retries + 1):
            try:
                teks = self._kirim(self._build_user_message(items))
                results = self._parse_response(teks, len(items))

                terlihat = {r.index for r in results}
                for i in range(len(items)):
                    if i not in terlihat:
                        results.append(TranslationResult(
                            index=i, title_id="", summary_id="",
                            ok=False, note="tidak dikembalikan model",
                        ))
                return sorted(results, key=lambda r: r.index)

            except urllib.error.HTTPError as exc:
                isi = exc.read().decode("utf-8", "replace")[:200]
                galat_terakhir = f"HTTP {exc.code}: {isi}"
                if exc.code == 404:
                    # Nama model salah. Mengulang tidak akan menolong.
                    log.error("model '%s' tidak dikenali. Periksa DCM_GEMINI_MODEL "
                              "terhadap daftar model di AI Studio.", self.model)
                    break
                if exc.code == 429:
                    log.warning("kuota Gemini tersendat, menunggu %.0f detik", tunggu)
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(tunggu)
                    tunggu *= 2
                    continue
                log.warning("terjemahan Gemini gagal: %s", galat_terakhir)
                break

            except (urllib.error.URLError, TimeoutError, ValueError,
                    json.JSONDecodeError, KeyError, IndexError) as exc:
                galat_terakhir = f"{type(exc).__name__}: {exc}"
                log.warning("terjemahan Gemini gagal (percobaan %s/%s): %s",
                            percobaan, self.max_retries, galat_terakhir)
                time.sleep(tunggu)
                tunggu *= 2

        return [
            TranslationResult(index=i, title_id="", summary_id="",
                              ok=False, note=galat_terakhir or "terjemahan gagal")
            for i in range(len(items))
        ]


def get_translator() -> Translator:
    """Pilih penyedia terjemahan sesuai DCM_TRANSLATE_PROVIDER.

    Nilai 'gemini' memakai Gemini. Nilai lain, atau kosong, memakai Anthropic
    seperti sebelumnya. Tidak ada perubahan perilaku bagi yang belum mengatur
    variabel ini.
    """
    penyedia = _env("TRANSLATE_PROVIDER", "anthropic").lower()

    if penyedia == "gemini":
        log.info("penyedia terjemahan: Gemini")
        return GeminiTranslator()

    log.info("penyedia terjemahan: Anthropic")
    return Translator()


if __name__ == "__main__":
    # Uji tanpa menyentuh basis data: python -m dcm.translate_gemini
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    contoh = [
        ("Bitcoin ETF inflows hit $1.2 billion as institutional demand returns",
         "Spot Bitcoin ETFs recorded their strongest weekly inflow since March, "
         "led by BlackRock's IBIT, as traders positioned ahead of the Fed meeting."),
        ("Ethereum staking withdrawals slow to three-month low",
         "Validators queuing to exit fell sharply this week, suggesting holders "
         "are content to keep earning yield despite flat price action."),
    ]

    penerjemah = GeminiTranslator()
    print(f"Model: {penerjemah.model}\n")

    for hasil in penerjemah.translate_batch(contoh):
        tanda = "OK " if hasil.ok else "GAGAL"
        print(f"[{tanda}] {hasil.title_id or hasil.note}")
        if hasil.summary_id:
            print(f"        {hasil.summary_id}\n")
