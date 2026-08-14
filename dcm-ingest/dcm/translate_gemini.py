"""
Penerjemah Inggris -> Indonesia memakai Gemini API.

Tidak butuh install apa pun: hanya modul bawaan Python (urllib, json).
Simpan file ini di folder dcm/ (sebelah file penerjemah Anthropic yang sudah ada).

Pengaturan lewat .env:
    GEMINI_API_KEY=xxxxxxxx
    GEMINI_MODEL=gemini-2.5-flash-lite      (opsional, ganti sesuai model free tier terbaru)
    GEMINI_RPM=10                            (opsional, jeda otomatis antar permintaan)

Cara uji cepat dari CMD:
    python dcm\\translate_gemini.py
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

INSTRUKSI = (
    "Anda penerjemah berita kripto untuk pembaca Indonesia. "
    "Terjemahkan judul dan ringkasan ke bahasa Indonesia yang wajar dan enak dibaca. "
    "Aturan: pertahankan istilah teknis dan nama entitas dalam bentuk asli "
    "(Bitcoin, Ethereum, staking, DeFi, ETF, SEC, nama bursa, nama tokoh). "
    "Jangan menambah informasi yang tidak ada di teks asli. "
    "Jangan menambah tanda kutip, tanda baca hiasan, atau catatan penerjemah. "
    "Judul dibuat ringkas seperti judul berita, tanpa titik di akhir. "
    "Angka, satuan mata uang, dan tanggal dipertahankan apa adanya. "
    "Jika teks sudah berbahasa Indonesia, kembalikan apa adanya tanpa diubah."
)


class GeminiError(RuntimeError):
    """Gagal menerjemahkan. Pemanggil sebaiknya membiarkan artikel tetap pending."""


def _api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise GeminiError("GEMINI_API_KEY belum diisi di .env")
    return key


def _model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()


def _jeda_detik() -> float:
    """Jeda minimal antar permintaan supaya tidak kena batas per menit."""
    try:
        rpm = float(os.getenv("GEMINI_RPM", "10"))
    except ValueError:
        rpm = 10.0
    return 60.0 / rpm if rpm > 0 else 0.0


_terakhir_dipanggil = 0.0


def _tahan_laju() -> None:
    global _terakhir_dipanggil
    jeda = _jeda_detik()
    selisih = time.time() - _terakhir_dipanggil
    if selisih < jeda:
        time.sleep(jeda - selisih)
    _terakhir_dipanggil = time.time()


def _panggil_gemini(prompt: str, percobaan: int = 4) -> str:
    """Kirim satu permintaan ke Gemini, kembalikan teks jawaban mentah."""
    url = f"{BASE_URL}/{_model()}:generateContent"
    badan = {
        "systemInstruction": {"parts": [{"text": INSTRUKSI}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    data = json.dumps(badan).encode("utf-8")

    tunggu = 2.0
    galat_terakhir = ""

    for _ in range(percobaan):
        _tahan_laju()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": _api_key(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                hasil = json.loads(resp.read().decode("utf-8"))
            bagian = hasil["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in bagian).strip()

        except urllib.error.HTTPError as e:
            isi = e.read().decode("utf-8", "replace")[:300]
            galat_terakhir = f"HTTP {e.code}: {isi}"
            # 429 = kuota habis, 5xx = gangguan sementara -> coba lagi
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(tunggu)
                tunggu *= 2
                continue
            raise GeminiError(galat_terakhir) from e

        except (urllib.error.URLError, TimeoutError, KeyError, IndexError) as e:
            galat_terakhir = f"{type(e).__name__}: {e}"
            time.sleep(tunggu)
            tunggu *= 2

    raise GeminiError(f"gagal setelah {percobaan} percobaan. {galat_terakhir}")


def _ambil_json(teks: str):
    """Bersihkan pagar ``` kalau model tetap menambahkannya, lalu parse."""
    bersih = teks.strip()
    if bersih.startswith("```"):
        bersih = bersih.split("```")[1]
        if bersih.lstrip().lower().startswith("json"):
            bersih = bersih.lstrip()[4:]
    try:
        return json.loads(bersih.strip())
    except json.JSONDecodeError as e:
        raise GeminiError(f"jawaban bukan JSON yang sah: {bersih[:200]}") from e


def terjemahkan(judul: str, ringkasan: str = "") -> dict:
    """
    Terjemahkan satu artikel.
    Kembalikan {"judul": ..., "ringkasan": ...}.
    Lempar GeminiError kalau gagal, supaya artikel tidak terbit setengah jadi.
    """
    prompt = (
        "Terjemahkan ke bahasa Indonesia. "
        'Balas HANYA objek JSON dengan kunci "judul" dan "ringkasan".\n\n'
        f"judul: {judul}\n"
        f"ringkasan: {ringkasan}"
    )
    hasil = _ambil_json(_panggil_gemini(prompt))
    if not isinstance(hasil, dict) or "judul" not in hasil:
        raise GeminiError(f"struktur jawaban tidak sesuai: {hasil}")
    return {
        "judul": str(hasil.get("judul", "")).strip(),
        "ringkasan": str(hasil.get("ringkasan", "")).strip(),
    }


def terjemahkan_banyak(artikel: list[dict], per_batch: int = 8) -> list[dict]:
    """
    Terjemahkan beberapa artikel sekaligus untuk menghemat kuota harian.

    Masukan : [{"id": 1, "judul": "...", "ringkasan": "..."}, ...]
    Keluaran: [{"id": 1, "judul": "...", "ringkasan": "..."}, ...]

    Batch yang gagal dilewati (artikel tetap pending), batch lain tetap jalan.
    """
    keluaran: list[dict] = []

    for i in range(0, len(artikel), per_batch):
        potongan = artikel[i : i + per_batch]
        muatan = [
            {
                "id": a.get("id"),
                "judul": a.get("judul") or a.get("title") or "",
                "ringkasan": a.get("ringkasan") or a.get("summary") or "",
            }
            for a in potongan
        ]
        prompt = (
            "Terjemahkan setiap item ke bahasa Indonesia. "
            "Balas HANYA array JSON berisi objek dengan kunci "
            '"id", "judul", dan "ringkasan". '
            "Pertahankan nilai id persis seperti masukan.\n\n"
            + json.dumps(muatan, ensure_ascii=False)
        )
        try:
            hasil = _ambil_json(_panggil_gemini(prompt))
            if isinstance(hasil, dict):
                hasil = hasil.get("items") or hasil.get("hasil") or []
            for baris in hasil:
                if isinstance(baris, dict) and baris.get("judul"):
                    keluaran.append(
                        {
                            "id": baris.get("id"),
                            "judul": str(baris["judul"]).strip(),
                            "ringkasan": str(baris.get("ringkasan", "")).strip(),
                        }
                    )
        except GeminiError as e:
            print(f"  [lewat] batch {i // per_batch + 1} gagal: {e}")

    return keluaran


if __name__ == "__main__":
    # Uji cepat: python dcm\translate_gemini.py
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    print(f"Model  : {_model()}")
    print(f"API key: {'ada' if os.getenv('GEMINI_API_KEY') else 'BELUM ADA'}\n")

    contoh = terjemahkan(
        "Bitcoin ETF inflows hit $1.2 billion as institutional demand returns",
        "Spot Bitcoin ETFs recorded their strongest weekly inflow since March, "
        "led by BlackRock's IBIT, as traders positioned ahead of the Fed meeting.",
    )
    print("Judul    :", contoh["judul"])
    print("Ringkasan:", contoh["ringkasan"])
