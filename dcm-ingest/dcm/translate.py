"""Terjemahan judul dan penulisan ulang ringkasan memakai Claude.

Ada perbedaan yang penting di modul ini, dan perbedaan itu disengaja.

  Judul       -> DITERJEMAHKAN. Judul terlalu pendek untuk ditulis ulang tanpa
                 mengubah maknanya, dan mengutip judul beserta tautan balik
                 adalah praktik lazim di seluruh dunia agregasi berita.

  Ringkasan   -> DITULIS ULANG, bukan diterjemahkan. Model membaca kutipan
                 feed lalu menyusun dua kalimat orisinal dalam bahasa
                 Indonesia. Hasilnya karya baru, bukan salinan berbahasa lain
                 dari tulisan penerbit.

Perbedaan itu bukan kehati-hatian berlebihan. Menerjemahkan badan artikel
lalu menerbitkannya adalah pembuatan karya turunan, dan hak itu ada pada
pemegang hak cipta. Menulis ringkasan sendiri dari kutipan yang memang
disediakan penerbit berada di wilayah yang jauh lebih aman.

Sumber berbahasa Indonesia sama sekali tidak melewati modul ini. Empat dari
tujuh sumber sudah berbahasa Indonesia, jadi biaya API turun sekitar 55
persen hanya karena melewatkan mereka.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from anthropic import Anthropic, APIError

from .settings import get_settings, glossary_config

log = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Hasil terjemahan satu item."""

    index: int
    title_id: str
    summary_id: str
    ok: bool = True
    note: str = ""


def _build_glossary_block() -> str:
    """Susun glosarium menjadi bagian prompt.

    Dibangun sekali per proses. Glosarium inilah yang membedakan hasil yang
    terbaca seperti tulisan wartawan kripto Indonesia dari hasil yang terbaca
    seperti keluaran penerjemah otomatis.
    """
    glossary = glossary_config()

    keep = ", ".join(glossary.get("keep", []))
    translate = "\n".join(
        f"  {en} -> {idn}" for en, idn in (glossary.get("translate") or {}).items()
    )
    institutions = "\n".join(
        f"  {abbr} -> {full}" for abbr, full in (glossary.get("institutions") or {}).items()
    )

    style = glossary.get("style", {})
    headline_rules = "\n".join(f"  - {rule}" for rule in style.get("headline", []))
    summary_rules = "\n".join(f"  - {rule}" for rule in style.get("summary", []))

    return f"""<glosarium>
BIARKAN DALAM BAHASA INGGRIS (istilah ini sudah jadi kosakata sehari-hari
pembaca kripto Indonesia; menerjemahkannya justru terasa janggal):
{keep}

WAJIB DITERJEMAHKAN (istilah keuangan umum yang punya padanan mapan):
{translate}

NAMA LEMBAGA (jangan diterjemahkan; beri keterangan pada penyebutan pertama):
{institutions}
</glosarium>

<aturan_judul>
{headline_rules}
</aturan_judul>

<aturan_ringkasan>
{summary_rules}
</aturan_ringkasan>"""


SYSTEM_PROMPT = """Anda editor bahasa di Daily Crypto Media, media berita aset \
kripto berbahasa Indonesia yang terbit di Jakarta. Pembaca Anda investor ritel \
dan profesional keuangan Indonesia.

Anda menerima item berita berbahasa Inggris dari kantor berita mitra. Untuk \
setiap item, kerjakan dua hal yang berbeda:

1. JUDUL — terjemahkan ke bahasa Indonesia. Pertahankan makna dan penekanannya. \
Jangan menambah atau mengurangi informasi.

2. RINGKASAN — JANGAN diterjemahkan. Baca kutipannya, lalu TULIS SENDIRI dua \
kalimat orisinal dalam bahasa Indonesia yang menjelaskan apa yang terjadi dan \
mengapa itu penting bagi pembaca Indonesia. Susun kalimat baru, bukan versi \
berbahasa Indonesia dari kalimat penerbit. Bila kutipannya terlalu tipis untuk \
diringkas dengan jujur, kembalikan string kosong untuk ringkasan. Jangan \
mengarang detail yang tidak ada pada bahan.

Jangan pernah menambahkan pendapat, prediksi harga, atau nasihat investasi.

Balas HANYA dengan larik JSON, tanpa pengantar dan tanpa pagar kode:
[{"i": 0, "judul": "...", "ringkasan": "..."}, ...]

Bidang "i" wajib sama persis dengan nomor item yang diberikan."""


class Translator:
    """Pembungkus Claude untuk terjemahan judul dan penulisan ringkasan.

    Item diproses per kelompok agar model melihat beberapa berita sekaligus.
    Selain memangkas biaya token, konteks kelompok juga membantu konsistensi
    istilah antar item dalam satu putaran polling.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "DCM_ANTHROPIC_API_KEY belum diisi. Salin .env.example menjadi "
                ".env lalu isi kuncinya."
            )
        self.client = Anthropic(api_key=key)
        self.model = model or settings.translate_model
        self.batch_size = settings.translate_batch_size
        self.max_retries = settings.translate_max_retries
        self._glossary_block = _build_glossary_block()

    # -- pembentukan permintaan -------------------------------------------

    def _build_user_message(self, items: list[tuple[str, str]]) -> str:
        """items: daftar (judul, kutipan) berbahasa Inggris."""
        blocks = []
        for i, (title, excerpt) in enumerate(items):
            blocks.append(
                f"<item i=\"{i}\">\n"
                f"<judul_asli>{title}</judul_asli>\n"
                f"<kutipan_asli>{excerpt or '(tidak ada kutipan)'}</kutipan_asli>\n"
                f"</item>"
            )
        return f"{self._glossary_block}\n\n<berita>\n" + "\n".join(blocks) + "\n</berita>"

    @staticmethod
    def _parse_response(text: str, expected: int) -> list[TranslationResult]:
        """Urai balasan model menjadi daftar hasil.

        Model diminta membalas JSON murni, tetapi pagar kode sesekali tetap
        muncul, jadi dibersihkan dulu sebelum diurai.
        """
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("larik JSON tidak ditemukan pada balasan model")

        payload = json.loads(cleaned[start : end + 1])

        results: list[TranslationResult] = []
        for row in payload:
            idx = int(row.get("i", -1))
            if not 0 <= idx < expected:
                continue
            results.append(TranslationResult(
                index=idx,
                title_id=(row.get("judul") or "").strip(),
                summary_id=(row.get("ringkasan") or "").strip(),
            ))
        return results

    # -- api publik --------------------------------------------------------

    def translate_batch(self, items: list[tuple[str, str]]) -> list[TranslationResult]:
        """Terjemahkan satu kelompok. items: daftar (judul, kutipan)."""
        if not items:
            return []

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": self._build_user_message(items)}],
                )
                text = "".join(
                    block.text for block in response.content
                    if getattr(block, "type", "") == "text"
                )
                results = self._parse_response(text, len(items))

                # Item yang tidak dikembalikan model diisi penanda gagal agar
                # pemanggil tidak perlu menebak indeks mana yang hilang.
                seen = {r.index for r in results}
                for i in range(len(items)):
                    if i not in seen:
                        results.append(TranslationResult(
                            index=i, title_id="", summary_id="",
                            ok=False, note="tidak dikembalikan model",
                        ))
                return sorted(results, key=lambda r: r.index)

            except (APIError, ValueError, json.JSONDecodeError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("terjemahan gagal (percobaan %s/%s): %s",
                            attempt, self.max_retries, last_error)

        return [
            TranslationResult(index=i, title_id="", summary_id="",
                              ok=False, note=last_error)
            for i in range(len(items))
        ]

    def translate_articles(self, articles: list) -> int:
        """Terjemahkan daftar objek Article di tempat.

        Artikel berbahasa Indonesia dilewati: judulnya dipakai apa adanya dan
        kutipan feed dijadikan ringkasan. Mengembalikan jumlah artikel yang
        berhasil diproses.
        """
        from .models import ArticleStatus  # impor lokal, hindari lingkar

        pending = [a for a in articles if a.lang_src != "id" and not a.title_id]
        local = [a for a in articles if a.lang_src == "id" and not a.title_id]

        # Sumber lokal: tanpa panggilan API sama sekali.
        for article in local:
            article.title_id = article.title_src
            article.summary_id = article.excerpt_src[:220]
            article.translated_at = datetime.now(timezone.utc)
            article.translate_model = "tanpa-terjemahan"
            article.status = ArticleStatus.TRANSLATED

        processed = len(local)

        for start in range(0, len(pending), self.batch_size):
            chunk = pending[start : start + self.batch_size]
            payload = [(a.title_src, a.excerpt_src) for a in chunk]
            results = self.translate_batch(payload)

            for result in results:
                article = chunk[result.index]
                if result.ok and result.title_id:
                    article.title_id = result.title_id
                    article.summary_id = result.summary_id
                    article.translated_at = datetime.now(timezone.utc)
                    article.translate_model = self.model
                    article.status = ArticleStatus.TRANSLATED
                    processed += 1
                else:
                    article.status = ArticleStatus.FAILED
                    article.error_note = result.note or "terjemahan gagal"

            log.info("kelompok %s: %s dari %s item diterjemahkan",
                     start // self.batch_size + 1,
                     sum(1 for r in results if r.ok), len(chunk))

        return processed
